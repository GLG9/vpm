"""Discord-neutrale Formatierung von Plan- und Änderungsnachrichten."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from vp_10e_plan import EventKind, PlanEvent, Profile

WEEKDAYS_LONG = (
    "Montag",
    "Dienstag",
    "Mittwoch",
    "Donnerstag",
    "Freitag",
    "Samstag",
    "Sonntag",
)
WEEKDAYS_SHORT = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
MAX_EMBED_FIELDS = 25
MAX_EMBED_CHARS = 6000
MAX_FIELD_NAME_CHARS = 256
MAX_FIELD_VALUE_CHARS = 1024


@dataclass(frozen=True)
class NotificationField:
    name: str
    value: str
    inline: bool = False


@dataclass(frozen=True)
class NotificationSpec:
    title: str
    description: str
    color: int
    fields: tuple[NotificationField, ...]
    footer: str
    delivery_keys: tuple[str, ...] = ()


class DeliveryLike(Protocol):
    status: str
    event: PlanEvent


def _split_text(value: str, limit: int) -> list[str]:
    """Teilt Text bevorzugt an Zeilenumbrüchen und garantiert das Limit."""

    parts: list[str] = []
    current = ""
    for line in value.splitlines() or [""]:
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
            current = ""
        while len(line) > limit:
            parts.append(line[:limit])
            line = line[limit:]
        current = line
    if current or not parts:
        parts.append(current)
    return parts


def paginate_fields(
    fields: Sequence[NotificationField],
    *,
    title: str,
    description: str,
    footer: str,
) -> list[tuple[NotificationField, ...]]:
    """Teilt Felder nach allen relevanten Discord-Embed-Grenzen auf."""

    normalized: list[NotificationField] = []
    for field in fields:
        name = field.name[:MAX_FIELD_NAME_CHARS]
        for index, value in enumerate(
            _split_text(field.value, MAX_FIELD_VALUE_CHARS)
        ):
            part_name = name
            if index:
                suffix = " (Fortsetzung)"
                part_name = f"{name[: MAX_FIELD_NAME_CHARS - len(suffix)]}{suffix}"
            normalized.append(
                NotificationField(part_name, value, inline=field.inline)
            )

    fixed_chars = len(title) + len(description) + len(footer)
    pages: list[tuple[NotificationField, ...]] = []
    current: list[NotificationField] = []
    current_chars = fixed_chars
    for field in normalized:
        field_chars = len(field.name) + len(field.value)
        if current and (
            len(current) >= MAX_EMBED_FIELDS
            or current_chars + field_chars > MAX_EMBED_CHARS
        ):
            pages.append(tuple(current))
            current = []
            current_chars = fixed_chars
        current.append(field)
        current_chars += field_chars
    if current:
        pages.append(tuple(current))
    return pages


def block_label(start_period: int, end_period: int) -> str:
    """Ordnet Stunden dem schulischen Zweierblock zu."""

    start_block = (start_period + 1) // 2
    end_block = (end_period + 1) // 2
    if start_block == end_block:
        return f"{start_block}. Block"
    return f"{start_block}.–{end_block}. Block"


def german_date(day: dt.date) -> str:
    return f"{WEEKDAYS_LONG[day.weekday()]}, {day:%d.%m.%Y}"


def _field_for_delivery(delivery: DeliveryLike) -> NotificationField:
    event = delivery.event
    time = ""
    if event.start_time or event.end_time:
        time = f" · {event.start_time or '--'}–{event.end_time or '--'}"
    name = f"{block_label(event.start_period, event.end_period)}{time}"

    if delivery.status == "resolved":
        lines = [
            "✅ Änderung aufgehoben",
            f"{event.course} findet wieder regulär statt.",
        ]
    elif event.kind is EventKind.CANCELLATION:
        lines = [f"❌ {event.course} fällt aus"]
    elif event.kind is EventKind.SELF_STUDY:
        lines = [f"🧑‍💻 {event.course}: Selbststudium"]
    elif event.kind is EventKind.MOVED:
        lines = [f"↔️ {event.course} wurde verlegt"]
    elif event.kind is EventKind.ROOM_CHANGE:
        lines = [f"🚪 {event.course}: Raumänderung"]
    elif event.kind is EventKind.SUBSTITUTION:
        lines = [f"🔄 {event.course}: Vertretung"]
    else:
        lines = [f"ℹ️ {event.course}: Hinweis"]

    if delivery.status != "resolved":
        if event.teacher_changed and event.teacher:
            lines.append(f"👩‍🏫 {event.original_teacher} → {event.teacher}")
        elif event.original_teacher and not event.info:
            lines.append(f"👩‍🏫 {event.original_teacher}")
        if event.subject_changed and event.subject and event.subject != "---":
            lines.append(f"📚 Neues Fach: {event.subject}")
        if event.room_changed and event.room:
            lines.append(f"📍 Neuer Raum: {event.room}")
        if event.info:
            lines.append(f"📝 {event.info}")
    return NotificationField(name=name, value="\n".join(lines))


def _compact_info(event: PlanEvent, *, cancellation: bool = False) -> str:
    """Macht den bereits vom Plan gelieferten Hinweis push-tauglich."""

    info = event.info.strip()
    if cancellation and info.casefold().startswith(event.course.casefold()):
        info = info[len(event.course) :].strip(" :-–")
    return info


def _preview(value: str, limit: int = 280) -> str:
    """Hält Push-Texte kurz, ohne die wichtige erste Information zu verlieren."""

    return value if len(value) <= limit else f"{value[: limit - 1].rstrip()}…"


def _self_study_info(event: PlanEvent) -> str:
    info = _compact_info(event)
    marker = "selbststudium"
    if info.casefold().startswith(marker):
        return info[len(marker) :].lstrip(" :;-–")
    return info


def _alert_title(delivery: DeliveryLike) -> str:
    event = delivery.event
    if delivery.status == "resolved":
        prefix = "✅ Entwarnung"
    elif event.kind in {EventKind.CANCELLATION, EventKind.SELF_STUDY}:
        prefix = "🚨 Ausfall"
        if event.kind is EventKind.SELF_STUDY and event.info:
            prefix = f"{prefix} – {_preview(_self_study_info(event), 55)}"
    elif event.kind is EventKind.SUBSTITUTION:
        prefix = "🔄 Vertretung"
    elif event.kind is EventKind.MOVED:
        prefix = "↔️ Verlegung"
    elif event.kind is EventKind.ROOM_CHANGE:
        prefix = "🚪 Raumwechsel"
    else:
        prefix = "ℹ️ Hinweis"
    return f"{prefix} · {event.profile_label}"


def _compact_delivery_line(delivery: DeliveryLike) -> str:
    event = delivery.event
    block = block_label(event.start_period, event.end_period)
    if delivery.status == "resolved":
        return _preview(
            f"✅ {block}: {event.course} findet wieder regulär statt."
        )
    if event.kind is EventKind.CANCELLATION:
        result = _compact_info(event, cancellation=True) or "fällt aus"
        return _preview(f"❌ {block}: {event.course} – {result}")
    if event.kind is EventKind.SELF_STUDY:
        result = _self_study_info(event) or "Selbststudium"
        return _preview(f"🧑‍💻 {block}: {event.course} – {result}")
    if event.kind is EventKind.SUBSTITUTION:
        result = (
            f"{event.original_teacher} → {event.teacher}"
            if event.teacher_changed and event.teacher
            else _compact_info(event) or "Vertretung"
        )
        return _preview(f"🔄 {block}: {event.course} – {result}")
    if event.kind is EventKind.MOVED:
        return _preview(
            f"↔️ {block}: {event.course} – {_compact_info(event) or 'verlegt'}"
        )
    if event.kind is EventKind.ROOM_CHANGE:
        result = f"Raum {event.room}" if event.room else "Raumänderung"
        return _preview(f"🚪 {block}: {event.course} – {result}")
    return _preview(
        f"ℹ️ {block}: {event.course} – {_compact_info(event)}"
    )


def _color(status: str, kind: EventKind) -> int:
    if status == "resolved":
        return 0x2ECC71
    return {
        EventKind.CANCELLATION: 0xE74C3C,
        EventKind.SELF_STUDY: 0x95A5A6,
        EventKind.ROOM_CHANGE: 0x3498DB,
    }.get(kind, 0xF39C12)


def build_notification_specs(
    deliveries: Sequence[DeliveryLike],
) -> list[NotificationSpec]:
    """Erzeugt Discord-neutrale Nachrichten innerhalb aller Embed-Limits."""

    if not deliveries:
        return []
    return [
        NotificationSpec(
            title=_alert_title(delivery),
            description=(
                f"{german_date(delivery.event.day)}\n\n"
                f"{_compact_delivery_line(delivery)}"
            ),
            color=_color(delivery.status, delivery.event.kind),
            fields=(),
            footer=(
                f"Planstand: {delivery.event.plan_timestamp or 'unbekannt'}"
            ),
            delivery_keys=(delivery.event.key,),
        )
        for delivery in deliveries
    ]


def build_overview_specs(
    profile: Profile,
    events: Sequence[PlanEvent],
    notes: Sequence[str] = (),
    exams: Sequence[str] = (),
) -> list[NotificationSpec]:
    sorted_events = sorted(events, key=lambda event: (event.day, event.start_period))
    if not sorted_events:
        fields = [NotificationField("Status", "✅ Keine Vertretungen")]
        color = 0x2ECC71
        footer = "Stand des letzten erfolgreichen Abrufs"
    else:
        fields = [
            NotificationField(
                (
                    f"{WEEKDAYS_SHORT[event.day.weekday()]}, {event.day:%d.%m.}"
                    f" · {block_label(event.start_period, event.end_period)}"
                ),
                _field_for_delivery(
                    type("Overview", (), {"status": "new", "event": event})()
                ).value,
            )
            for event in sorted_events
        ]
        color = max(
            (_color("new", event.kind) for event in sorted_events),
            key=lambda value: value == 0xE74C3C,
        )
        footer = f"Planstand: {sorted_events[-1].plan_timestamp or 'unbekannt'}"
    if notes:
        fields.append(
            NotificationField(
                "Allgemeine Hinweise", "\n".join(f"• {item}" for item in notes)
            )
        )
    if exams:
        fields.append(
            NotificationField(
                "Klausuren", "\n".join(f"• {item}" for item in exams)
            )
        )
    title = f"📋 07:00-Überblick · {profile.label}"
    description = "Aktive Vertretungen der nächsten zehn Schultage"
    return [
        NotificationSpec(
            title=title,
            description=description,
            color=color,
            fields=page,
            footer=footer,
        )
        for page in paginate_fields(
            fields,
            title=title,
            description=description,
            footer=footer,
        )
    ]
