# Vertretungsplan Monitor Bot

Dieser Bot überwacht den Vertretungsplan einer Schule und sendet Änderungen in einen Discord-Channel. Er lädt regelmäßig die XML-Daten des Plans und speichert Ausfälle oder Raumänderungen.

## Kurz für Junior Developer

*Die wichtigsten Dateien*
- **vp_10e_plan.py** – Funktionen zum Laden und Parsen des Vertretungsplans.
- **bot_with_plan_monitor.py** – Enthält den Discord-Bot. 
- **tests/** – Pytest-Tests, die Parsing und Hilfsfunktionen abdecken.

*Setup*
1. Python ≥ 3.11 installieren.
2. Abhängigkeiten mit `pip install -r requirements.txt` installieren.
3. Eine `.env` Datei anlegen und folgende Variablen setzen:
   ```
   VP_USER=...
   VP_PASS=...
   VP_BASE_URL=...
   DISCORD_TOKEN=...
   PLAN_CHANNEL_ID=...
   ```
   # optionale Einstellungen
   CHECK_SECONDS=30   # wie oft der Plan abgefragt wird
   SHOW_TICK=false   # Kopfzeile bei jedem Tick senden
   SHOW_RES=false    # XML-Auszug der Klasse 10E ins Log schreiben
   FAKE_DATE=YYYYMMDD  # Testdatum statt heutigem Datum
4. Tests ausführen: `pytest`.
5. Bot starten: `python bot_with_plan_monitor.py`.

Der Bot nutzt `tasks.loop` und schreibt Log-Dateien nach `logs/`.

## Für nicht-technische Leser

Dieses Projekt ist ein kleiner Helfer für Discord. Er prüft regelmäßig den offiziellen Vertretungsplan der Klasse und meldet automatisch Änderungen (zum Beispiel Ausfälle oder Raumwechsel) in einem Discord-Channel. Dadurch wissen alle rechtzeitig Bescheid, ohne selbst den Plan zu kontrollieren.

