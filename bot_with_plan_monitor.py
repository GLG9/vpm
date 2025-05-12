# ------------------------------------------------------------
# bot_with_plan_monitor.py
# ------------------------------------------------------------
#!/usr/bin/env python3
"""Discord-Bot, der Vertretungsplan meldet – Ausfall nur einmal gesammelt, Plantage für n Tage, und Prune-Logs."""

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
if not TOKEN or CHANNEL_ID == 0:
    raise RuntimeError("DISCORD_TOKEN oder PLAN_CHANNEL_ID fehlt")

logging.basicConfig(
    level=logging.DEBUG,
    handlers=[logging.FileHandler("discord.log", mode="w", encoding="utf-8")],
    format="%(asctime)s %(levelname)s: %(message)s",
)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot("!", intents=intents)

# ---------------------------------------------------------------------------
# Log-Ordner & Utils
# ---------------------------------------------------------------------------

DIR = pathlib.Path(__file__).with_name("logs")
DIR.mkdir(exist_ok=True)

PF = lambda d: DIR / f"{d:%Y%m%d}.json"
load_json = lambda d: json.loads(PF(d).read_text()) if PF(d).exists() else None
save_json = lambda d, p: PF(d).write_text(json.dumps(p, ensure_ascii=False, indent=2))

# prune old logs
def last_schooldays(n: int = 10) -> Set[str]:
    days: List[dt.date] = []
    cur = dt.date.today()
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
            try:
                f.unlink()
            except OSError:
                pass

# alerts state
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

# digest
DIGEST = DIR / "last_digest.txt"
def read_digest() -> Optional[str]:
    try:
        return DIGEST.read_text().strip()
    except FileNotFoundError:
        return None
def write_digest(d: str) -> None:
    DIGEST.write_text(d)

# ---------------------------------------------------------------------------
# Anzeige-Hilfen
# ---------------------------------------------------------------------------

def fmt(e: dict) -> str:
    fach = f"AUSFALL ({e['kurs']})" if e["fach"] == "---" else e["fach"]
    return f"{e['stunde']} {e['beginn'] or '--'}-{e['ende'] or '--'} {fach} {e['raum'] or ''} {e['lehrer'] or ''}"

def room_change(old: dict, new: dict) -> Optional[str]:
    key_old = (old.get("kurs") or old.get("fach") or "").upper()
    key_new = (new.get("kurs") or new.get("fach") or "").upper()
    r_old   = (old.get("raum") or "").strip().upper()
    r_new   = (new.get("raum") or "").strip().upper()
    if old["stunde"] == new["stunde"] and key_old == key_new and r_old != r_new:
        return f"Raumänderung: Stunde {new['stunde']} {key_new} {old.get('raum') or '---'} → {new.get('raum') or '---'}"
    return None

# ---------------------------------------------------------------------------
# Haupt-Task
# ---------------------------------------------------------------------------

@tasks.loop(seconds=60)
async def check() -> None:
    ch = bot.get_channel(CHANNEL_ID)
    if ch is None:
        return

    alerts = load_alerts()
    day_offset = 0
    misses = 0
    head = f"🕒 Tick {dt.datetime.now():%H:%M:%S}"
    out: List[str] = []

    today_str = dt.date.today().strftime("%Y%m%d")
    seen_hours = alerts.get(today_str, set())

    # scan next ~10 schooldays
    while misses < 16:
        day = dt.date.today() + dt.timedelta(day_offset)
        day_offset += 1
        try:
            xml = await asyncio.to_thread(vp.lade_plan, day)
            misses = 0
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                misses += 1
                continue
            logging.exception("HTTP-Fehler")
            break

        mine = [e for e in vp.parse_xml(xml) if vp.mine(e)]
        prev = load_json(day)

        # always save on first encounter
        if prev is None:
            save_json(day, mine)
            out.append(f"📅 {day:%d.%m.%Y} – neuer Plan ({len(mine)})")
            continue

        # collect changes
        rc_msgs: List[str] = []
        for n in mine:
            o = next(
                (o for o in prev
                 if o["stunde"] == n["stunde"]
                 and (o["kurs"] or o["fach"]) == (n["kurs"] or n["fach"])),
                None
            )
            if o:
                txt = room_change(o, n)
                if txt:
                    rc_msgs.append(f"• {txt}")

        if rc_msgs:
            out.append(f"📅 {day:%d.%m.%Y}\n" + "\n".join(rc_msgs))
            save_json(day, mine)
        else:
            # only for today, collect new Ausfall
            if day == dt.date.today():
                new_entries = [
                    n for n in mine
                    if n["fach"] == "---"
                    and n["stunde"] not in seen_hours
                    and any(o for o in prev if o["stunde"] == n["stunde"] and o["fach"] != "---")
                ]
                if new_entries:
                    lines = [
                        f"• Ausfall in Stunde {n['stunde']} – {n['info']}"
                        for n in new_entries
                    ]
                    out.append(f"📅 {day:%d.%m.%Y}\n" + "\n".join(lines))
                    # persist seen
                    seen_hours |= {n["stunde"] for n in new_entries}
                    alerts[today_str] = seen_hours
                    save_alerts(alerts)
                    save_json(day, mine)

    prune_logs(10)

    # pure Ausfall-only suppression
    if out and all(line.startswith("• Ausfall") or line.startswith("📅") for line in out):
        # if only Ausfall blocks, send just head
        send_out = []
        for block in out:
            # detect if block contains Raumänderung, keep only first block with Ausfall
            if "Raumänderung" not in block:
                send_out = [block]
                break
        #if send_out:
            #await ch.send(f"{head}\n" + send_out[0])
        #else:
            #await ch.send(head)
        return

    # duplicate suppression
    if not out:
        #await ch.send(head)
        return
    payload = "\n".join(out)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    if digest == read_digest():
        #await ch.send(head)
        return
    write_digest(digest)
    #await ch.send("\n".join([head, *out]))

# ---------------------------------------------------------------------------
# Commands & Startup
# ---------------------------------------------------------------------------

@bot.command(name="heute")
async def c_today(ctx):
    xml = await asyncio.to_thread(vp.lade_plan, dt.date.today())
    mine = [e for e in vp.parse_xml(xml) if vp.mine(e)]
    if not mine:
        return await ctx.send("Keine Stunden für deine Kurse.")
    mine.sort(key=lambda x: x["stunde"])
    await ctx.send(
        "\n".join(
            [f"📅 **Plan heute – {dt.date.today():%d.%m.%Y}**"] +
            [f"• {fmt(e)}" for e in mine]
        )
    )

@bot.command(name="morgen")
async def c_morgen(ctx):
    tomorrow = dt.date.today() + dt.timedelta(1)
    try:
        xml = await asyncio.to_thread(vp.lade_plan, tomorrow)
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            return await ctx.send("Morgen ist Frei :)")
        raise
    mine = [e for e in vp.parse_xml(xml) if vp.mine(e)]
    if not mine:
        return await ctx.send("Keine Stunden für deine Kurse.")
    mine.sort(key=lambda x: x["stunde"])
    await ctx.send(
        "\n".join(
            [f"📅 **Plan morgen – {tomorrow:%d.%m.%Y}**"] +
            [f"• {fmt(e)}" for e in mine]
        )
    )

@bot.command(name="übermorgen", aliases=["uebermorgen"])
async def c_uebermorgen(ctx):
    day = dt.date.today() + dt.timedelta(2)
    try:
        xml = await asyncio.to_thread(vp.lade_plan, day)
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            return await ctx.send("Übermorgen ist Frei :)")
        raise
    mine = [e for e in vp.parse_xml(xml) if vp.mine(e)]
    if not mine:
        return await ctx.send("Keine Stunden für deine Kurse.")
    mine.sort(key=lambda x: x["stunde"])
    await ctx.send(
        "\n".join(
            [f"📅 **Plan übermorgen – {day:%d.%m.%Y}**"] +
            [f"• {fmt(e)}" for e in mine]
        )
    )

@bot.command(name="überübermorgen", aliases=["ueberuebermorgen"])
async def c_uebermorgen(ctx):
    day = dt.date.today() + dt.timedelta(3)
    try:
        xml = await asyncio.to_thread(vp.lade_plan, day)
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            return await ctx.send("Überübermorgen ist Frei :)")
        raise
    mine = [e for e in vp.parse_xml(xml) if vp.mine(e)]
    if not mine:
        return await ctx.send("Keine Stunden für deine Kurse.")
    mine.sort(key=lambda x: x["stunde"])
    await ctx.send(
        "\n".join(
            [f"📅 **Plan überübermorgen – {day:%d.%m.%Y}**"] +
            [f"• {fmt(e)}" for e in mine]
        )
    )

@bot.event
async def on_ready():
    print("Bot online:", bot.user)
    if not check.is_running():
        check.start()

if __name__ == "__main__":
    bot.run(TOKEN)
