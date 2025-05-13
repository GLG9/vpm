#!/usr/bin/env python3
# ------------------------------------------------------------
# bot_with_plan_monitor.py
# ------------------------------------------------------------
"""Discord-Bot, der Vertretungsplan meldet – Ausfall nur einmal gesammelt,
Plantage für n Tage, Prune-Logs und per .env konfigurierbares Tick-Header."""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import logging
import os
import pathlib
from typing import Dict, List, Set, Optional

import discord
import requests
from discord.ext import commands, tasks
from dotenv import load_dotenv

import vp_10e_plan as vp
vp.mine = vp.keep

# ---------------------------------------------------------------------------
# Discord-Init
# ---------------------------------------------------------------------------
load_dotenv()
TOKEN      = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("PLAN_CHANNEL_ID", "0"))
SHOW_TICK  = os.getenv("SHOW_TICK", "false").lower() == "true"

if not TOKEN or CHANNEL_ID == 0:
    raise RuntimeError("DISCORD_TOKEN oder PLAN_CHANNEL_ID fehlt")

logging.basicConfig(
    level=logging.INFO,
    handlers=[logging.FileHandler("discord.log", mode="w", encoding="utf-8")],
    format="%(asctime)s %(levelname)s: %(message)s",
)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot("!", intents=intents)

# Steuerung via .env:
# SHOW_TICK=true/false  → Kopfzeile senden, auch bei keinen Änderungen
# SHOW_RES=true/false   → Parsed-Response für Klasse 10E jeden Tag ins Log
SHOW_TICK = os.getenv("SHOW_TICK", "false").lower() == "true"
SHOW_RES  = os.getenv("SHOW_RES",  "false").lower() == "true"

# ---------------------------------------------------------------------------
# Log-Ordner & Utils
# ---------------------------------------------------------------------------
DIR = pathlib.Path(__file__).with_name("logs")
DIR.mkdir(exist_ok=True)

PF = lambda d: DIR / f"{d:%Y%m%d}.json"
load_json = lambda d: json.loads(PF(d).read_text()) if PF(d).exists() else None
save_json = lambda d, p: PF(d).write_text(json.dumps(p, ensure_ascii=False, indent=2))

def last_schooldays(n: int = 10) -> Set[str]:
    days, cur = [], dt.date.today()
    while len(days) < n:
        if cur.weekday() < 5:
            days.append(cur)
        cur -= dt.timedelta(1)
    return {d.strftime("%Y%m%d") for d in days}

def prune_logs(n: int = 10) -> None:
    keep = last_schooldays(n)
    for f in DIR.glob("*.json"):
        name = f.stem
        try:
            d = dt.datetime.strptime(name, "%Y%m%d").date()
        except ValueError:
            continue
        if name not in keep and d < dt.date.today():
            try: f.unlink()
            except OSError: pass

ALERTS = DIR / "alerts.json"
def load_alerts() -> Dict[str, Set[int]]:
    try:
        data = json.loads(ALERTS.read_text())
        return {day: set(hours) for day, hours in data.items()}
    except FileNotFoundError:
        return {}
def save_alerts(alerts: Dict[str, Set[int]]):
    serial = {day: sorted(list(hours)) for day, hours in alerts.items()}
    ALERTS.write_text(json.dumps(serial, ensure_ascii=False, indent=2))

DIGEST = DIR / "last_digest.txt"
def read_digest() -> Optional[str]:
    try: return DIGEST.read_text().strip()
    except FileNotFoundError: return None
def write_digest(d: str) -> None:
    DIGEST.write_text(d)

# ---------------------------------------------------------------------------
# Anzeige-Hilfen
# ---------------------------------------------------------------------------
def fmt(e: dict) -> str:
    fach = f"AUSFALL ({e['kurs']})" if e["fach"] == "---" else e["fach"]
    return f"{e['stunde']} {e['beginn'] or '--'}-{e['ende'] or '--'} {fach} {e['raum'] or ''} {e['lehrer'] or ''}"

def room_change(old: dict, new: dict) -> Optional[str]:
    ko, kn = (old.get("kurs") or old.get("fach") or "").upper(), (new.get("kurs") or new.get("fach") or "").upper()
    ro, rn = (old.get("raum") or "").strip().upper(), (new.get("raum") or "").strip().upper()
    if old["stunde"] == new["stunde"] and ko == kn and ro != rn:
        return f"Raumänderung: Stunde {new['stunde']} {kn} {old.get('raum') or '---'} → {new.get('raum') or '---'}"
    return None

# ---------------------------------------------------------------------------
# Haupt-Task
# ---------------------------------------------------------------------------
@tasks.loop(seconds=20)
async def check() -> None:
    ch = bot.get_channel(CHANNEL_ID)
    if ch is None:
        return

    alerts = load_alerts()
    today_str = dt.date.today().strftime("%Y%m%d")
    seen_hours = alerts.get(today_str, set())
    day_offset = 0
    misses = 0
    head = f"🕒 Tick {dt.datetime.now():%H:%M:%S}" if SHOW_TICK else ""
    out: List[str] = []

    while misses < 16:
        day = dt.date.today() + dt.timedelta(day_offset)
        day_offset += 1
        try:
            # lade rohe XML
            xml = await asyncio.to_thread(vp.lade_plan, day)
            misses = 0
            if SHOW_RES:
                # nur den <Kl Kurz="10E">-Block extrahieren und loggen
                import xml.etree.ElementTree as ET
                root = ET.fromstring(xml)
                kl10e = next(
                    (k for k in root.findall(".//Kl")
                    if (k.findtext("Kurz") or "").strip().upper() == "10E"),
                    None
                )
                if kl10e is not None:
                    snippet = ET.tostring(kl10e, encoding="unicode")
                    logging.info(f"[Raw 10E XML {day:%Y%m%d}] {snippet}")
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                misses += 1
                continue
            logging.exception("HTTP-Fehler")
            break

        # parse erst nach dem Logging
        mine = [e for e in vp.parse_xml(xml) if vp.mine(e)]

        prev = load_json(day)

        if prev is None:
            save_json(day, mine)
            out.append(f"📅 {day:%d.%m.%Y} – neuer Plan ({len(mine)})")
            logging.info(f"[Neuer Plan] {day:%Y-%m-%d} – {len(mine)} Einträge geladen")
            continue

        # Raumänderungen und Ausfälle
        rc_msgs: List[str] = []
        # 1) neue Ausfälle sammeln
        ausfall = [
            e for e in mine
            if e["fach"] == "---" and e["stunde"] not in seen_hours
        ]
        for e in ausfall:
            rc_msgs.append(f"• Ausfall in Stunde {e['stunde']} – {e['info'] or ''} - {e.get('kurs') or ''}")
            seen_hours.add(e["stunde"])
        if ausfall:
            alerts[today_str] = seen_hours
            save_alerts(alerts)
            save_json(day, mine)
        else:
            # 2) Raumänderungen prüfen, wenn keine neuen Ausfälle
            for e in mine:
                o = next(
                    (
                        o for o in prev
                        if o["stunde"] == e["stunde"]
                        and (o["kurs"] or o["fach"]) == (e["kurs"] or e["fach"])
                    ),
                    None
                )
                if o:
                    txt = room_change(o, e)
                    if txt:
                        rc_msgs.append(f"• {txt}")

        if rc_msgs:
            block = f"📅 {day:%d.%m.%Y}\n" + "\n".join(rc_msgs)
            out.append(block)
            logging.info(f"[Planänderung] {day:%Y-%m-%d}\n" + "\n".join(rc_msgs))
            save_json(day, mine)


    prune_logs(10)

    # Nur reine Ausfall-Blöcke (ohne Raumänderungen) → nur ersten Ausfall senden
    if out and all(("Ausfall" in block) and ("Raumänderung" not in block) for block in out):
        block = next(block for block in out if "Ausfall" in block)
        text = f"{head}\n{block}" if SHOW_TICK else block
        await ch.send(text)
        return

    # Duplikate unterdrücken
#    if not out:
#        return
#    payload = "\n".join(out)
#    digest = hashlib.sha256(payload.encode()).hexdigest()
#    if digest == read_digest():
#        return
#    write_digest(digest)
#
#    # Sende alles (mit Kopf, falls SHOW_TICK)
#    text = f"{head}\n{payload}" if SHOW_TICK else payload
#    await ch.send(text)
# duplicate suppression
    payload = "\n".join(out)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    if digest == read_digest():
        # kein neuer Digest
        if SHOW_TICK:
            await ch.send(head)
        return
    write_digest(digest)

    # wenn Änderungen vorliegen, sende sie (mit Kopf, falls SHOW_TICK)
    if out:
        text = f"{head}\n{payload}" if SHOW_TICK else payload
        await ch.send(text)
    # falls keine Änderungen, aber SHOW_TICK, sende nur das Tick-Header
    elif SHOW_TICK:
        await ch.send(head)

# ---------------------------------------------------------------------------
# Slash-/Text-Befehle
# ---------------------------------------------------------------------------
async def _send(ctx: commands.Context, day: dt.date, title: str) -> None:
    try:
        xml = await asyncio.to_thread(vp.lade_plan, day)
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            await ctx.send(f"{title} ist Frei :)")
            return
        await ctx.send("Plan nicht verfügbar.")
        return

    mine = [e for e in vp.parse_xml(xml) if vp.mine(e)]
    if not mine:
        await ctx.send("Keine Stunden für deine Kurse.")
        return

    mine.sort(key=lambda x: x["stunde"])
    header = f"📅 **{title} – {day:%d.%m.%Y}**"
    lines = [f"• {fmt(e)}" for e in mine]
    await ctx.send("\n".join([header, *lines]))

@bot.command(name="heute")
async def c_today(ctx):     await _send(ctx, dt.date.today(), "Plan heute")
@bot.command(name="morgen")
async def c_morgen(ctx):    await _send(ctx, dt.date.today() + dt.timedelta(1), "Plan morgen")
@bot.command(name="übermorgen", aliases=["uebermorgen"])
async def c_over(ctx):      await _send(ctx, dt.date.today() + dt.timedelta(2), "Plan übermorgen")
@bot.command(name="überübermorgen", aliases=["ueberuebermorgen"])
async def c_over2(ctx):     await _send(ctx, dt.date.today() + dt.timedelta(3), "Plan überübermorgen")

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
@bot.event
async def on_ready():
    print("Bot online:", bot.user)
    if not check.is_running():
        check.start()

if __name__ == "__main__":
    bot.run(TOKEN)
