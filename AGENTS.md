# Project Guidelines

This repository implements a Discord bot that monitors the class substitution plan (Vertretungsplan).

## Coding conventions
- Use **Python 3.11+** and follow the general [PEP 8](https://peps.python.org/pep-0008/) style guidelines.
- Keep modules small and focused. `vp_10e_plan.py` is the parsing/fetching module while `bot_with_plan_monitor.py` contains the bot logic.
- Prefer explicit type hints. The existing code utilises `typing` annotations.
- Configuration and secrets are expected in a `.env` file. Do not hard code credentials.
- Log files (`discord.log`, `error.log`, JSON logs) are written to the `logs/` directory. Keep output UTF‑8 encoded.
- Tests live in `tests/` and are run with `pytest`.

## Architecture Overview
- **vp_10e_plan.py** – loads the XML schedule, parses it and filters relevant entries. This module can be used standalone.
- **bot_with_plan_monitor.py** – Discord bot that periodically checks for changes using `tasks.loop`. It sends messages about new entries or changes to a configured channel.
- **logs/** – contains daily JSON dumps of parsed data, an `alerts.json` file for duplicate suppression and `last_digest.txt` for message digests.
- **tests/** – pytest unit tests verifying parsing, filtering and helper behaviour.
- **requirements.txt** – minimal dependency list.

## Repository Tree
```
.
├── bot_with_plan_monitor.py  # Discord bot entry point
├── vp_10e_plan.py            # fetch and filter schedule
├── logs/                     # stored plan data and alerts
├── tests/                    # pytest suite
├── requirements.txt          # dependencies
```
