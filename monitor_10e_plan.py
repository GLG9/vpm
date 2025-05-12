#!/usr/bin/env python3
"""monitor_10e_plan.py
Script, das bei jedem Aufruf:
  1. den Vertretungsplan 10E holt (nur eigene Kurse),
  2. ihn in   logs/YYYYMMDD.json   speichert,
  3. den aktuellen mit dem gespeicherten Plan vergleicht
     und Änderungen auf STDOUT ausgibt.

* Für das minutengenaue Ausführen einfach per Cron (Linux)
    * * * * * /usr/bin/python3 /pfad/monitor_10e_plan.py
  oder per „Aufgabe erstellen“ in der Windows Aufgabenplanung
    (Auslöser: täglich, alle 1 Minute wiederholen).

Benötigt vp_10e_plan.py im selben Verzeichnis.
"""

import datetime as dt
import json
import pathlib
import sys
from vp_10e_plan import lade_plan, parse_xml, keep   # aus vorigem Script

LOG_DIR = pathlib.Path(__file__).with_name("logs")

def load_previous(path: pathlib.Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"⚠️  Konnte alte Logdatei nicht lesen: {exc}", file=sys.stderr)
        return None

def save_plan(path: pathlib.Path, plan: list[dict]):
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

def diff_plans(old: list[dict], new: list[dict]):
    """Gibt (entfernt, hinzu) zurück."""
    to_key = lambda d: json.dumps(d, sort_keys=True, ensure_ascii=True)
    old_set = {to_key(x) for x in old}
    new_set = {to_key(x) for x in new}
    removed = [json.loads(x) for x in (old_set - new_set)]
    added   = [json.loads(x) for x in (new_set - old_set)]
    return removed, added

def main():
    datum = dt.date.today()
    try:
        xml_text = lade_plan(datum)
        plan_all = parse_xml(xml_text, "10E")
    except Exception as exc:
        print(f"❌ Fehler beim Laden/Parsen: {exc}", file=sys.stderr)
        sys.exit(1)

    plan = [e for e in plan_all if keep(e)]

    log_file = LOG_DIR / f"{datum:%Y%m%d}.json"
    prev_plan = load_previous(log_file)

    if prev_plan is None:
        print("▶️  Erste Speicherung für heute.")
        save_plan(log_file, plan)
        return

    removed, added = diff_plans(prev_plan, plan)
    if not removed and not added:
        print("✅ Keine Änderungen im Plan.")
    else:
        print("🔄 Änderungen erkannt!")
        if added:
            print("\n➕ Neu hinzugekommen:")
            for d in added:
                print("   ", d)
        if removed:
            print("\n➖ Entfernt:")
            for d in removed:
                print("   ", d)
        print("\n📋 Neuer Plan:")
        for p in plan:
            print("   ", p)
        print("\n📋 Alter Plan:")
        for p in prev_plan:
            print("   ", p)
        save_plan(log_file, plan)

if __name__ == "__main__":
    main()
