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

## Luca-Stundenplan für Jarvis

Optional kann der Bot einen authentifizierten, nur lesbaren JSON-Endpunkt für
Gians Profil bereitstellen. Dafür `SCHEDULE_API_TOKEN` auf ein langes eigenes
Zufallstoken setzen. Standardmäßig bindet der Dienst nur an `127.0.0.1:8094`;
für Jarvis auf einem anderen Host muss `SCHEDULE_API_HOST` auf eine private
Schnittstellenadresse gesetzt und der Port dort erreichbar gemacht werden.
Der Endpunkt `/api/v1/schedule/YYYY-MM-DD` gibt ausschließlich das Profil
`luca` zurück. Andere Profile werden nie über diesen Endpunkt ausgewählt.
Nicht veröffentlichte Tagespläne liefern `published: false`.

Auf dem Jarvis-Host müssen `JARVIS_VPM_SCHEDULE_URL` (Basis-URL ohne den
API-Pfad), `JARVIS_VPM_SCHEDULE_TOKEN` und `JARVIS_VPM_SCHEDULE_OWNER` gesetzt
werden. Der letzte Wert muss exakt der Jarvis-Benutzername, die E-Mail-Adresse
oder die interne Benutzer-ID von Gian Luca sein; so bleibt die Stundenplanregel
auf sein Planner-Konto begrenzt. Beide Hosts müssen den API-Port über ein
privates Netz erreichen können. Das Token wird getrennt in den beiden
Service-Umgebungen gespeichert und gehört nicht in Git.

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
