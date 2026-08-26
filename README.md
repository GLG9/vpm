# Vertretungsplan-Monitor für Discord

Der Bot überwacht die offiziellen Indiware-Mobilpläne mehrerer persönlicher
Profile. Er erkennt Ausfälle, Selbststudium, Lehrer-, Fach- und Raumwechsel,
Verlegungen sowie Hinweise und fasst aufeinanderfolgende Stunden zu Blöcken
zusammen.

## Verhalten

- Prüfung montags bis freitags von 06:30 bis 15:00 Uhr alle 60 Sekunden.
- Vorschau auf die nächsten zehn Schultage; Wochenenden und die in
  `Klassen.xml` aufgeführten freien Tage werden übersprungen.
- Pro Datei zuerst eine kleine `HEAD`-Anfrage. Die große XML wird nur bei
  geändertem `ETag`, Änderungsdatum oder geänderter Dateigröße geladen.
- Neue, geänderte und aufgehobene Vertretungen werden genau einmal gemeldet.
- Um 07:00 Uhr kann pro Profil ein Überblick aktiviert werden.
- Der Zustand wird atomar in `state/monitor.json` gespeichert und überlebt
  Neustarts und Discord-Reconnects.

## Einrichtung

Voraussetzung ist Python 3.11 oder neuer.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
```

Danach in `.env` mindestens `VP_PASS`, `DISCORD_TOKEN` und
`PLAN_CHANNEL_ID` eintragen. Zugangsdaten und Token werden niemals im Code
oder in Git gespeichert.

Start:

```bash
.venv/bin/python bot_with_plan_monitor.py
```

Der Bot steuert das Zeitfenster selbst; ein Cronjob ist dafür nicht nötig.
Auf einem Server kann der Prozess trotzdem durch systemd, Docker oder einen
anderen Prozessmanager dauerhaft gestartet werden.

## Profile

`MONITOR_PROFILES` enthält beliebig viele Profil-IDs. Für eine neue ID
`max` werden folgende Variablen verwendet:

```dotenv
PROFILE_MAX_LABEL=Max · 12/2
PROFILE_MAX_SOURCE_CLASSES=12/2
PROFILE_MAX_DISPLAY_CLASS=12/2
PROFILE_MAX_DAILY_OVERVIEW=true
PROFILE_MAX_COURSES=CHE1@Gruß;eng1@Kiss
```

Kurs und ursprüngliche Lehrkraft werden exakt gepaart. Groß-/Kleinschreibung
ist absichtlich relevant, weil beispielsweise `CHE1` und `che1` verschiedene
Kurse sind. Mehrere Quellklassen werden kommasepariert angegeben.

Alle Profile senden in denselben `PLAN_CHANNEL_ID`.

## Befehle

```text
!heute luca
!morgen jasper
!übermorgen 8g
```

Ohne oder mit unbekanntem Profil zeigt der Bot die gültigen Profilnamen an.

## Sicher testen

Alle Tests:

```bash
.venv/bin/pytest -q
```

Ein echter Abruf der Schul-XML ohne Discord-Versand und ohne Veränderung des
produktiven Zustands:

```bash
DRY_RUN=true .venv/bin/python bot_with_plan_monitor.py
```

Der Dry-Run gibt die erkannten Vertretungen und Hinweise nur im Terminal aus.
