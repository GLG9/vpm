"""Validierte Konfiguration für beliebig viele Monitorprofile."""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from vp_10e_plan import CourseRef, Profile

DEFAULT_COURSES: dict[str, tuple[CourseRef, ...]] = {
    "luca": tuple(
        CourseRef(*item)
        for item in (
            ("CHE1", "Gruß"),
            ("DEU2", "Glad"),
            ("MAT1", "Muns"),
            ("eng1", "Kiss"),
            ("eth3", "Zeitz"),
            ("geo1", "Thüne"),
            ("ges4", "Mada"),
            ("inf1", "Voß"),
            ("kun2", "KugJ"),
            ("phy2", "Luth"),
            ("spo3_3KS", "Btrm"),
        )
    ),
    "jasper": tuple(
        CourseRef(*item)
        for item in (
            ("BIO4", "Drei"),
            ("CHE1", "Gruß"),
            ("DEU1", "Got"),
            ("eng1", "Kiss"),
            ("eth3", "Zeitz"),
            ("geo1", "Thüne"),
            ("ges1", "Schm"),
            ("kun2", "KugJ"),
            ("mat3", "Marx"),
            ("spo4_3TT", "SchJ"),
            ("wil1", "Zeitz"),
        )
    ),
    "8g": tuple(
        CourseRef(*item)
        for item in (
            ("Bio", "Hoy"),
            ("Che", "Lonz"),
            ("Deu", "Ilgst"),
            ("Eng", "Hert"),
            ("Geo", "Möw"),
            ("Ges", "Horn"),
            ("Mat", "Köp"),
            ("Mus", "Ber"),
            ("Phy", "Beck"),
            ("Rus", "Möw"),
            ("8eth7", "BeKe"),
            ("spm3", "From"),
        )
    ),
}

DEFAULT_PROFILE_VALUES = {
    "luca": ("Gian · 12/2", "12/2", "12/2", True),
    "jasper": ("Jasper · 12/2", "12/1", "12/2", True),
    "8g": ("8G", "08G", "8G", False),
}


@dataclass(frozen=True)
class AppConfig:
    username: str
    password: str
    base_url: str
    discord_token: str
    channel_id: int
    profiles: tuple[Profile, ...]
    check_seconds: float
    active_start: dt.time
    active_end: dt.time
    overview_time: dt.time
    lookahead_school_days: int
    timezone: ZoneInfo
    state_file: Path
    dry_run: bool


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "ja", "on"}:
        return True
    if normalized in {"0", "false", "no", "nein", "off"}:
        return False
    raise ValueError(f"Ungültiger Boolean-Wert: {value}")


def _time(value: str, name: str) -> dt.time:
    try:
        hour, minute = value.split(":")
        if len(hour) != 2 or len(minute) != 2:
            raise ValueError
        return dt.time(int(hour), int(minute))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} muss HH:MM entsprechen") from exc


def _courses(value: str) -> tuple[CourseRef, ...]:
    result: list[CourseRef] = []
    for item in value.split(";"):
        item = item.strip()
        if not item:
            continue
        try:
            code, teacher = item.split("@", 1)
        except ValueError as exc:
            raise ValueError(
                f"Kurs '{item}' muss als Kurs@Lehrkraft angegeben werden"
            ) from exc
        result.append(CourseRef(code, teacher))
    if not result:
        raise ValueError("Ein Profil benötigt mindestens einen Kurs")
    return tuple(result)


def _profile(profile_id: str, env: Mapping[str, str]) -> Profile:
    key = profile_id.upper().replace("-", "_")
    defaults = DEFAULT_PROFILE_VALUES.get(profile_id)
    if defaults:
        default_label, default_sources, default_display, default_overview = defaults
    else:
        default_label = profile_id
        default_sources = ""
        default_display = profile_id
        default_overview = False

    sources_raw = env.get(f"PROFILE_{key}_SOURCE_CLASSES", default_sources)
    source_classes = tuple(
        item.strip() for item in sources_raw.split(",") if item.strip()
    )
    if not source_classes:
        raise ValueError(f"PROFILE_{key}_SOURCE_CLASSES fehlt")

    courses_raw = env.get(f"PROFILE_{key}_COURSES")
    courses = (
        _courses(courses_raw)
        if courses_raw is not None
        else DEFAULT_COURSES.get(profile_id, ())
    )
    if not courses:
        raise ValueError(f"PROFILE_{key}_COURSES fehlt")

    return Profile(
        profile_id=profile_id,
        label=env.get(f"PROFILE_{key}_LABEL", default_label),
        display_class=env.get(
            f"PROFILE_{key}_DISPLAY_CLASS", default_display
        ),
        source_classes=source_classes,
        courses=courses,
        daily_overview=_bool(
            env.get(f"PROFILE_{key}_DAILY_OVERVIEW"), default_overview
        ),
    )


def load_config(
    environ: Mapping[str, str] | None = None,
    *,
    require_discord: bool | None = None,
) -> AppConfig:
    env = dict(os.environ if environ is None else environ)
    dry_run = _bool(env.get("DRY_RUN"), False)
    if require_discord is None:
        require_discord = not dry_run

    missing = [
        name for name in ("VP_USER", "VP_PASS", "VP_BASE_URL") if not env.get(name)
    ]
    if missing:
        raise ValueError(f"Fehlende Konfiguration: {', '.join(missing)}")

    token = env.get("DISCORD_TOKEN", "")
    try:
        channel_id = int(env.get("PLAN_CHANNEL_ID", "0"))
    except ValueError as exc:
        raise ValueError("PLAN_CHANNEL_ID muss eine Zahl sein") from exc
    if require_discord and (not token or not channel_id):
        raise ValueError("DISCORD_TOKEN oder PLAN_CHANNEL_ID fehlt")

    profile_ids = tuple(
        item.strip().casefold()
        for item in env.get("MONITOR_PROFILES", "luca,jasper,8g").split(",")
        if item.strip()
    )
    if not profile_ids:
        raise ValueError("MONITOR_PROFILES enthält kein Profil")

    try:
        check_seconds = float(env.get("CHECK_SECONDS", "60"))
        lookahead = int(env.get("LOOKAHEAD_SCHOOL_DAYS", "10"))
    except ValueError as exc:
        raise ValueError("CHECK_SECONDS/LOOKAHEAD_SCHOOL_DAYS ungültig") from exc
    if check_seconds < 1 or lookahead < 1:
        raise ValueError("Prüfintervall und Vorschau müssen positiv sein")

    timezone = ZoneInfo(env.get("TIMEZONE", "Europe/Berlin"))
    return AppConfig(
        username=env["VP_USER"],
        password=env["VP_PASS"],
        base_url=env["VP_BASE_URL"],
        discord_token=token,
        channel_id=channel_id,
        profiles=tuple(_profile(profile_id, env) for profile_id in profile_ids),
        check_seconds=check_seconds,
        active_start=_time(env.get("ACTIVE_START", "06:30"), "ACTIVE_START"),
        active_end=_time(env.get("ACTIVE_END", "15:00"), "ACTIVE_END"),
        overview_time=_time(
            env.get("DAILY_OVERVIEW_TIME", "07:00"), "DAILY_OVERVIEW_TIME"
        ),
        lookahead_school_days=lookahead,
        timezone=timezone,
        state_file=Path(env.get("STATE_FILE", "state/monitor.json")),
        dry_run=dry_run,
    )
