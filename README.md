# Vertretungsplan‑Bot 10E

Ein kleiner, aber leistungsfähiger **Discord‑Bot**, der den Vertretungs‑ und Raum‑plan für die Klasse **10 E** automatisch überwacht, Änderungen erkennt und sie als Meldung in einen Discord‑Channel pusht. Geschrieben in *Python 3* – ohne Datenbank, alles wird lokal als JSON geloggt.

> Entwickelt & gepflegt von **Gianluca** "GLG9"   🛠️  – Feedback / Pull‑Requests sind willkommen!

---

## Funktions‑Highlights

| Feature                      | Beschreibung                                                                              |
| ---------------------------- | ----------------------------------------------------------------------------------------- |
| 🕒 **Tick‑Anzeige**          | Regelmäßiger "Heartbeat" im Channel (abschaltbar per `.env`).                             |
| 🗂️ **Mehr­tages‑Überblick** | Lädt automatisch die Pläne für heute + bis zu 15 Folgetage.                                |
| 🔔 **Intelligente Alerts**   | Meldet *Ausfall* und *Raum­änderung* **nur einmal**, filtert nach eigenen Kursen/Fächern. |
| 🧹 **Log‑Rotation**          | Alte Log‑Dateien (> 10 Schul­tage) werden selbst­ständig entfernt.                        |
| ⚠️ **Auto‑Restart**          | Fängt Crashes ab, schreibt `error.log` und startet den Bot neu.                           |
| 🛡️ **.env‑Config**          | Token & Zugangsdaten bleiben außerhalb des Repos.                                         |

---

## Installation

```bash
# 1) Klonen
$ git clone https://github.com/GLG9/vpm.git
$ cd vpm-bot

# 2) Virtuelle Umgebung (empfohlen)
$ python -m venv .venv
$ source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3) Abhängigkeiten
$ pip install -r requirements.txt
```

### .env anlegen

```ini
DISCORD_TOKEN = "<dein Discord Bot Token>"
PLAN_CHANNEL_ID = 123456789012345678   # Channel, in den gepostet wird

# optionale Schalter
SHOW_TICK = false   # true = Heartbeat anzeigen
SHOW_RES  = false   # true = kompletten XML‑Block loggen
```

> **Wichtig:**  `.env` unbedingt in `.gitignore` lassen, damit kein Geheimnis ins Repo wandert!

---

## Starten

```bash
python bot_with_plan_monitor.py
```

Für den Dauerbetrieb empfiehlt sich ein **systemd‑Service** (`vpm_bot.service`) – Beispiel­unit liegt im Repo.

---

## Nutzung im Discord

| Befehl            | Wirkung                 |
| ----------------- | ----------------------- |
| `!heute`          | Plan für heute anzeigen |
| `!morgen`         | Plan für morgen         |
| `!übermorgen`     | +2 Tage                 |
| `!überübermorgen` | +3 Tage                 |

Die automatische Hintergrundprüfung läuft alle *30 Sekunden* und postet Änderungen sofort.

---

## Beitrag & Lizenz

Dieses Projekt steht unter der **MIT‑Lizenz**. Feel free to fork – PRs mit Bugfixes, neuen Features oder Docs sind gern gesehen. ✨

---

*Mit ❤️ codiert – viel Spaß & wenig Ausfälle!* ✌️
