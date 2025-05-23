#!/usr/bin/env python3
# ------------------------------------------------------------
# bot_with_plan_monitor.py
# ------------------------------------------------------------
"""
Discord-Bot, der den Vertretungsplan überwacht und Meldungen über
Änderungen sendet.  Ich kann auch den Plan für die nächsten Tage abrufen.
"""

from __future__ import annotations

import unicodedata as _ud
import asyncio
import datetime as dt
import hashlib
import json
import logging
import os
import pathlib
from typing import Dict, List, Set, Optional   # ← bleibt gleich, aber …

import discord
import requests
from discord.ext import commands, tasks
from dotenv import load_dotenv

import vp_10e_plan as vp
vp.mine = vp.keep
load_dotenv()

def _canon(s: str) -> str:
    """Unicode-normalisieren, überflüssige Leerzeichen killen."""
    return _ud.normalize("NFC", " ".join(s.split()))

######

# datetime → zentralisieren
import os
import datetime as dt, os, logging

_fake = os.getenv("FAKE_DATE")
if _fake:
    try:
        _fake_date = dt.datetime.strptime(_fake, "%Y%m%d").date()

        class _FakeDate(dt.date):
            @classmethod
            def today(cls):
                return _fake_date

        dt.date = _FakeDate        # type: ignore[attr-defined]
        logging.info("FAKE_DATE aktiv: %s", _fake)
    except ValueError:
        logging.warning("Ungültige FAKE_DATE=%s – echtes Datum wird benutzt", _fake)



######

# ---------------------------------------------------------------------------
# Discord-Init
# ---------------------------------------------------------------------------

TOKEN      = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("PLAN_CHANNEL_ID", "0"))
SHOW_TICK  = os.getenv("SHOW_TICK", "false").lower() == "true"

if not TOKEN or CHANNEL_ID == 0:
    raise RuntimeError("DISCORD_TOKEN oder PLAN_CHANNEL_ID fehlt")

logging.basicConfig(
    level=logging.INFO,
    handlers=[logging.FileHandler("discord.log", mode="a", encoding="utf-8")],  # ← mode="a"
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

# --------- Alerts verwalten -------------------------------------------------
KEEP_DAYS = 21 
DUP_DAYS  = 16   # innerhalb dieser Frist KEINE erneute Benachrichtigung                    # Meldungen nach 21 Tagen verwerfen

ALERTS = DIR / "alerts.json"
def load_alerts() -> dict[str, set[str]]:
    try:
        raw  = ALERTS.read_text(encoding="utf-8")
        if not raw.strip():                # leere Datei → neu beginnen
            return {}
        data = json.loads(raw)
        today = dt.date.today()
        fresh: dict[str, set[str]] = {}
        for day, msgs in data.items():
            try:
                if (today - dt.datetime.strptime(day, "%Y%m%d").date()).days <= KEEP_DAYS:
                    fresh[day] = set(msgs)
            except ValueError:
                continue
        return fresh
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
def save_alerts(alerts: Dict[str, Set[str]]) -> None:
    serial = {day: sorted(list(msgs)) for day, msgs in alerts.items()}
    # immer UTF-8 schreiben – unabhängig von der Windows-Codepage
    ALERTS.write_text(
        json.dumps(serial, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

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
@tasks.loop(seconds=60)
async def check() -> None:
    ch = bot.get_channel(CHANNEL_ID)
    if ch is None:
        return

    alerts    = load_alerts()
    today     = dt.date.today()
    today_str = today.strftime("%Y%m%d")

    # ► alle Meldungen der letzten DUP_DAYS sammeln
    recent_msgs: set[str] = set()
    for day, msgs in alerts.items():
        if (today - dt.datetime.strptime(day, "%Y%m%d").date()).days <= DUP_DAYS:
            recent_msgs |= msgs

    sent_msgs: set[str] = set(recent_msgs)  # wird unten erweitert
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

        # -------- Meldungen generieren ------------------------------------
        rc_msgs: list[str] = []

        # 1) Ausfälle
        for e in (en for en in mine if en["fach"] == "---"):
            raw  = (f"{day:%Y-%m-%d} ▸ Ausfall in Stunde {e['stunde']} – "
                f"{e['info'] or ''} - {e.get('kurs') or ''}")
            msg  = _canon(raw)
            if msg not in sent_msgs:
                rc_msgs.append(f"• {msg}")
                sent_msgs.add(msg)

        # 2) Raumänderungen
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
                    raw = f"{day:%Y-%m-%d} ▸ {txt}"
                    msg = _canon(raw)
                    if msg not in sent_msgs:
                        rc_msgs.append(f"• {msg}")
                        sent_msgs.add(msg)

        # erfolgreiche neue Meldungen persistieren
        # ► wirklich neue Meldungen des *heutigen* Laufs sichern
        if rc_msgs:
            new_today = sent_msgs - recent_msgs
            if new_today:
                alerts.setdefault(today_str, set()).update(new_today)
                save_alerts(alerts)
            save_json(day, mine)

        if rc_msgs:
            block = f"📅 {day:%d.%m.%Y}\n" + "\n".join(rc_msgs)
            out.append(block)
            logging.info(f"[Planänderung] {day:%Y-%m-%d}\n" + "\n".join(rc_msgs))
            save_json(day, mine)


    prune_logs(10)

    # Nur reine Ausfall-Blöcke (ohne Raumänderungen) → nur ersten Ausfall senden
    #if out and all(("Ausfall" in block) and ("Raumänderung" not in block) for block in out):
    #    block = next(block for block in out if "Ausfall" in block)
    #    text = f"{head}\n{block}" if SHOW_TICK else block
    #    await ch.send(text)
    #    return

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
    import time, traceback, datetime as dt

    while True:
        try:
            # *** PRO ITERATION EIN NEUER BOT ***
            intents = discord.Intents.default()
            intents.message_content = True
            bot = commands.Bot("!", intents=intents)

            # Commands/Events müssen nach der Instanziierung
            # erneut registriert werden:
            bot.add_command(c_today)
            bot.add_command(c_morgen)
            bot.add_command(c_over)
            bot.add_command(c_over2)
            bot.add_listener(on_ready)

            check.restart()     # Task an den neuen Bot binden
            bot.run(TOKEN)
            break                      # reguläres Ende

        except KeyboardInterrupt:      # sauber beenden (systemctl stop / Ctrl-C)
            break

        except discord.errors.LoginFailure as exc:
            # ungültiger Token → nicht endlos reconnecten
            with open("error.log", "a", encoding="utf-8") as fh:
                fh.write(
                    f"\n=== {dt.datetime.now():%Y-%m-%d %H:%M:%S} ===\n"
                    f"{exc}\n"
                )
            break          # -> Dienst bleibt gestoppt, bis Token gefixt ist
        except Exception:                  # andere Crashes → retry            
            with open("error.log", "a", encoding="utf-8") as fh:
                fh.write(
                    f"\n=== {dt.datetime.now():%Y-%m-%d %H:%M:%S} ===\n"
                    f"{traceback.format_exc()}\n"
                )
            time.sleep(15)             # 15 s Pause, dann neuer Versuch
