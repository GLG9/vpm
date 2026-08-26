# Project Guidelines

This repository implements a Discord bot that monitors the class substitution plan (Vertretungsplan).

## Coding conventions
- Use **Python 3.11+** and follow the general [PEP 8](https://peps.python.org/pep-0008/) style guidelines.
- Keep modules small and focused. `vp_10e_plan.py` is the parsing/fetching module while `bot_with_plan_monitor.py` contains the bot logic.
- Prefer explicit type hints. The existing code utilises `typing` annotations.
- Configuration and secrets are expected in a `.env` file. Do not hard code credentials.
- Runtime state and logs are written below `state/` and are ignored by Git. Keep output UTF‑8 encoded.
- Tests live in `tests/` and are run with `pytest`.

## Architecture Overview
- **vp_10e_plan.py** – fetches and parses official mobile XML schedules and filters profile-specific entries.
- **monitor_config.py** – validates environment configuration and profile/course selections.
- **monitor_service.py** – coordinates fingerprints, downloads, event diffs and overview scheduling.
- **monitor_state.py** – atomically persists observed and delivered event state.
- **notification_format.py** – creates Discord-neutral notification and overview specifications.
- **bot_with_plan_monitor.py** – Discord entry point, monitor loop and text commands.
- **state/** – ignored runtime state and logs.
- **tests/** – pytest unit tests verifying parsing, filtering and helper behaviour.
- **requirements.txt** – minimal dependency list.

## Repository Tree
```
.
├── bot_with_plan_monitor.py  # Discord bot entry point
├── monitor_config.py         # environment and profiles
├── monitor_service.py        # polling orchestration
├── monitor_state.py          # persistent delivery state
├── notification_format.py    # Discord-neutral formatting
├── vp_10e_plan.py            # fetch and parse schedules
├── state/                    # ignored runtime data
├── tests/                    # pytest suite
├── requirements.txt          # dependencies
```

## Server Operations

- The production LXC is reachable through the SSH host alias `test-vscode-tunnel`.
- VPM and Fux run as systemd services, not Docker containers. Check them with
  `ssh test-vscode-tunnel 'systemctl status vpm_bot.service fux.service'`.
- Both services should be `active` and `enabled`; VPM's service name is
  `vpm_bot.service`.
