"""Abruf, Parsing und Darstellung der Indiware-Mobilpläne."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from enum import Enum

import requests


def _clean(value: str | None) -> str:
    return unicodedata.normalize("NFC", " ".join((value or "").split()))


def _text(node: ET.Element, tag: str) -> str:
    return _clean(node.findtext(tag))


@dataclass(frozen=True)
class CourseRef:
    """Ein exakt ausgewählter Unterricht aus der App."""

    code: str
    teacher: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _clean(self.code))
        object.__setattr__(self, "teacher", _clean(self.teacher))


@dataclass(frozen=True)
class Profile:
    profile_id: str
    label: str
    display_class: str
    source_classes: tuple[str, ...]
    courses: tuple[CourseRef, ...]
    daily_overview: bool = False


class EventKind(str, Enum):
    CANCELLATION = "cancellation"
    SELF_STUDY = "self_study"
    MOVED = "moved"
    SUBSTITUTION = "substitution"
    ROOM_CHANGE = "room_change"
    NOTE = "note"


@dataclass(frozen=True)
class LessonBlock:
    profile_id: str
    profile_label: str
    display_class: str
    day: dt.date
    plan_timestamp: str
    lesson_nr: str
    occurrence: int
    course: str
    original_subject: str
    original_teacher: str
    start_period: int
    end_period: int
    start_time: str
    end_time: str
    subject: str
    teacher: str
    room: str
    info: str
    subject_changed: bool
    teacher_changed: bool
    room_changed: bool


@dataclass(frozen=True)
class PlanEvent(LessonBlock):
    kind: EventKind

    @property
    def key(self) -> str:
        return (
            f"{self.profile_id}:{self.day:%Y%m%d}:"
            f"{self.lesson_nr}:{self.occurrence}"
        )

    @property
    def version(self) -> str:
        payload = self.to_dict()
        # Der Veröffentlichungszeitpunkt ändert sich auch bei Anpassungen an
        # anderen Klassen. Nur der fachliche Ereignisinhalt erzeugt Updates.
        payload.pop("plan_timestamp", None)
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()

    def to_dict(self) -> dict:
        data = asdict(self)
        data["day"] = self.day.isoformat()
        data["kind"] = self.kind.value
        return data

    @classmethod
    def from_dict(cls, data: dict) -> PlanEvent:
        values = dict(data)
        values["day"] = dt.date.fromisoformat(values["day"])
        values["kind"] = EventKind(values["kind"])
        return cls(**values)


@dataclass(frozen=True)
class ProfilePlan:
    profile: Profile
    day: dt.date
    plan_timestamp: str
    blocks: tuple[LessonBlock, ...]
    events: tuple[PlanEvent, ...]
    general_notes: tuple[str, ...] = ()
    exams: tuple[str, ...] = ()


@dataclass(frozen=True)
class FileFingerprint:
    etag: str = ""
    last_modified: str = ""
    content_length: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> FileFingerprint:
        return cls(**data)


@dataclass(frozen=True)
class _Definition:
    nr: str
    code: str
    subject: str
    teacher: str


@dataclass(frozen=True)
class _Row:
    definition: _Definition
    period: int
    start: str
    end: str
    subject: str
    teacher: str
    room: str
    info: str
    subject_changed: bool
    teacher_changed: bool
    room_changed: bool

    @property
    def signature(self) -> tuple:
        return (
            self.definition.nr,
            self.subject,
            self.teacher,
            self.room,
            self.info,
            self.subject_changed,
            self.teacher_changed,
            self.room_changed,
        )


def _date_from_root(root: ET.Element) -> dt.date:
    head = root.find(".//Kopf")
    filename = _text(head if head is not None else root, "datei")
    match = re.search(r"(\d{8})", filename)
    if not match:
        raise ValueError("Plan enthält kein auswertbares Datum")
    value = match.group(1)
    return dt.date(int(value[:4]), int(value[4:6]), int(value[6:8]))


def parse_free_days(xml_bytes: bytes) -> set[dt.date]:
    root = ET.fromstring(xml_bytes)
    days: set[dt.date] = set()
    for node in root.findall(".//FreieTage/ft"):
        raw = _clean(node.text)
        try:
            days.add(dt.date(2000 + int(raw[:2]), int(raw[2:4]), int(raw[4:6])))
        except (ValueError, IndexError):
            continue
    return days


def _matching_definitions(klass: ET.Element, profile: Profile) -> dict[str, _Definition]:
    selected = {(course.code, course.teacher) for course in profile.courses}
    definitions: dict[str, _Definition] = {}
    for node in klass.findall("./Unterricht/Ue/UeNr"):
        nr = _clean(node.text)
        teacher = _clean(node.get("UeLe"))
        subject = _clean(node.get("UeFa"))
        group = _clean(node.get("UeGr"))
        code = group or subject
        if nr and (code, teacher) in selected:
            definitions[nr] = _Definition(nr, code, subject, teacher)
    return definitions


def _changed(node: ET.Element, tag: str, expected: str) -> bool:
    child = node.find(tag)
    return child is not None and child.get(expected) is not None


def _event_kind(block: LessonBlock) -> EventKind | None:
    info = block.info.casefold()
    if block.subject == "---" or "fällt aus" in info:
        return EventKind.CANCELLATION
    if info.startswith("selbst"):
        return EventKind.SELF_STUDY
    if "verlegt" in info:
        return EventKind.MOVED
    if block.subject_changed or block.teacher_changed:
        return EventKind.SUBSTITUTION
    if block.room_changed:
        return EventKind.ROOM_CHANGE
    if block.info:
        return EventKind.NOTE
    return None


def _rows_for_class(klass: ET.Element, profile: Profile) -> list[_Row]:
    definitions = _matching_definitions(klass, profile)
    rows: list[_Row] = []
    for node in klass.findall("./Pl/Std"):
        nr = _text(node, "Nr")
        definition = definitions.get(nr)
        if definition is None:
            continue
        try:
            period = int(_text(node, "St"))
        except ValueError:
            continue
        rows.append(
            _Row(
                definition=definition,
                period=period,
                start=_text(node, "Beginn"),
                end=_text(node, "Ende"),
                subject=_text(node, "Fa"),
                teacher=_text(node, "Le"),
                room=_text(node, "Ra"),
                info=_text(node, "If"),
                subject_changed=_changed(node, "Fa", "FaAe"),
                teacher_changed=_changed(node, "Le", "LeAe"),
                room_changed=_changed(node, "Ra", "RaAe"),
            )
        )
    return rows


def _group_rows(
    rows: Sequence[_Row],
    profile: Profile,
    day: dt.date,
    timestamp: str,
) -> list[LessonBlock]:
    unique = {
        (row.definition.nr, row.period, row.signature): row for row in rows
    }
    ordered = sorted(
        unique.values(), key=lambda row: (row.period, row.definition.nr)
    )
    grouped: list[list[_Row]] = []
    for row in ordered:
        match = next(
            (
                group
                for group in grouped
                if group[-1].signature == row.signature
                and group[-1].period + 1 == row.period
            ),
            None,
        )
        if match is None:
            grouped.append([row])
        else:
            match.append(row)

    occurrences: dict[str, int] = {}
    blocks: list[LessonBlock] = []
    for group in sorted(grouped, key=lambda item: (item[0].period, item[0].definition.nr)):
        first, last = group[0], group[-1]
        nr = first.definition.nr
        occurrence = occurrences.get(nr, 0) + 1
        occurrences[nr] = occurrence
        blocks.append(
            LessonBlock(
                profile_id=profile.profile_id,
                profile_label=profile.label,
                display_class=profile.display_class,
                day=day,
                plan_timestamp=timestamp,
                lesson_nr=nr,
                occurrence=occurrence,
                course=first.definition.code,
                original_subject=first.definition.subject,
                original_teacher=first.definition.teacher,
                start_period=first.period,
                end_period=last.period,
                start_time=first.start,
                end_time=last.end,
                subject=first.subject,
                teacher=first.teacher,
                room=first.room,
                info=first.info,
                subject_changed=first.subject_changed,
                teacher_changed=first.teacher_changed,
                room_changed=first.room_changed,
            )
        )
    return blocks


def _exam_lines(classes: Iterable[ET.Element], profile: Profile) -> tuple[str, ...]:
    selected_codes = {course.code for course in profile.courses}
    lines: list[str] = []
    for klass in classes:
        for exam in klass.findall("./Klausur"):
            course = _text(exam, "KlKurs")
            if course not in selected_codes:
                continue
            parts = [course]
            start = _text(exam, "KlBeginn")
            duration = _text(exam, "KlDauer")
            info = _text(exam, "KlInfo")
            if start:
                parts.append(start)
            if duration:
                parts.append(f"{duration} Min.")
            if info:
                parts.append(info)
            line = " · ".join(parts)
            if line not in lines:
                lines.append(line)
    return tuple(lines)


def parse_profile_plan(xml_bytes: bytes, profile: Profile) -> ProfilePlan:
    """Parst einen Tagesplan und filtert ihn für ein persönliches Profil."""

    root = ET.fromstring(xml_bytes)
    day = _date_from_root(root)
    head = root.find(".//Kopf")
    timestamp = _text(head if head is not None else root, "zeitstempel")
    wanted_classes = set(profile.source_classes)
    classes = [
        klass
        for klass in root.findall(".//Klassen/Kl")
        if _text(klass, "Kurz") in wanted_classes
    ]
    rows: list[_Row] = []
    for klass in classes:
        rows.extend(_rows_for_class(klass, profile))
    blocks = _group_rows(rows, profile, day, timestamp)
    events = tuple(
        PlanEvent(**asdict(block), kind=kind)
        for block in blocks
        if (kind := _event_kind(block)) is not None
    )
    notes = tuple(
        dict.fromkeys(
            _clean(node.text)
            for node in root.findall(".//ZiZeile")
            if _clean(node.text)
        )
    )
    return ProfilePlan(
        profile=profile,
        day=day,
        plan_timestamp=timestamp,
        blocks=tuple(blocks),
        events=events,
        general_notes=notes,
        exams=_exam_lines(classes, profile),
    )


def next_school_days(
    start: dt.date,
    count: int,
    free_days: set[dt.date] | None = None,
) -> list[dt.date]:
    free_days = free_days or set()
    result: list[dt.date] = []
    current = start
    while len(result) < count:
        if current.weekday() < 5 and current not in free_days:
            result.append(current)
        current += dt.timedelta(days=1)
    return result


def is_active_window(
    when: dt.datetime,
    start: dt.time,
    end: dt.time,
) -> bool:
    return when.weekday() < 5 and start <= when.time().replace(tzinfo=None) < end


class PlanClient:
    """Synchroner HTTP-Client; der Bot führt ihn über ``to_thread`` aus."""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        timeout: float = 10,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth = (username, password)
        self.timeout = timeout

    def _url(self, filename: str) -> str:
        return f"{self.base_url}/{filename}"

    def head_file(self, filename: str) -> FileFingerprint | None:
        response = requests.head(
            self._url(filename),
            auth=self.auth,
            timeout=self.timeout,
            allow_redirects=True,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return FileFingerprint(
            etag=response.headers.get("ETag", ""),
            last_modified=response.headers.get("Last-Modified", ""),
            content_length=response.headers.get("Content-Length", ""),
        )

    def get_file(self, filename: str) -> bytes:
        response = requests.get(
            self._url(filename), auth=self.auth, timeout=self.timeout
        )
        response.raise_for_status()
        return response.content

    def head_plan(self, day: dt.date) -> FileFingerprint | None:
        return self.head_file(f"PlanKl{day:%Y%m%d}.xml")

    def get_plan(self, day: dt.date) -> bytes:
        return self.get_file(f"PlanKl{day:%Y%m%d}.xml")
