from __future__ import annotations

import asyncio
import datetime as dt
import json
from zoneinfo import ZoneInfo

import pytest
import requests

from monitor_config import AppConfig, load_config
from monitor_service import MonitorService
from monitor_state import Delivery, MonitorState, StateStore, diff_events
from notification_format import build_notification_specs
from vp_10e_plan import (
    CourseRef,
    EventKind,
    FileFingerprint,
    Profile,
    is_active_window,
    next_school_days,
    parse_profile_plan,
)

BERLIN = ZoneInfo("Europe/Berlin")


def profile_8g(*, overview: bool = False) -> Profile:
    return Profile(
        profile_id="8g",
        label="8G",
        display_class="8G",
        source_classes=("08G",),
        courses=(CourseRef("8eth7", "BeKe"), CourseRef("spm3", "From")),
        daily_overview=overview,
    )


def profile_upper() -> Profile:
    return Profile(
        profile_id="luca",
        label="Gian · 12/2",
        display_class="12/2",
        source_classes=("12/2",),
        courses=(
            CourseRef("CHE1", "Gruß"),
            CourseRef("MAT1", "Muns"),
            CourseRef("eng1", "Kiss"),
            CourseRef("DEU1", "Got"),
        ),
        daily_overview=True,
    )


def xml_fixture(*, info: str = "8eth7 Frau Becker fällt aus") -> bytes:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<VpMobil>
  <Kopf><zeitstempel>26.08.2026, 06:27</zeitstempel><DatumPlan>Freitag, 28. August 2026</DatumPlan><datei>PlanKl20260828.xml</datei></Kopf>
  <FreieTage><ft>260831</ft></FreieTage>
  <Klassen>
    <Kl>
      <Kurz>08G</Kurz>
      <Unterricht>
        <Ue><UeNr UeLe="BeKe" UeFa="Eth" UeGr="8eth7">261</UeNr></Ue>
        <Ue><UeNr UeLe="Kos" UeFa="Spo" UeGr="spj3">267</UeNr></Ue>
      </Unterricht>
      <Pl>
        <Std><St>1</St><Beginn>07:15</Beginn><Ende>08:00</Ende><Fa FaAe="FaGeaendert">---</Fa><Ku2>8eth7</Ku2><Le LeAe="LeGeaendert"/><Ra RaAe="RaGeaendert"/><Nr>261</Nr><If>{info}</If></Std>
        <Std><St>2</St><Beginn>08:00</Beginn><Ende>08:45</Ende><Fa FaAe="FaGeaendert">---</Fa><Ku2>8eth7</Ku2><Le LeAe="LeGeaendert"/><Ra RaAe="RaGeaendert"/><Nr>261</Nr><If>{info}</If></Std>
        <Std><St>5</St><Beginn>11:00</Beginn><Ende>11:45</Ende><Fa>spj3</Fa><Ku2>spj3</Ku2><Le>Kos</Le><Ra>TH3</Ra><Nr>267</Nr><If/></Std>
      </Pl>
    </Kl>
    <Kl>
      <Kurz>12/2</Kurz>
      <Unterricht>
        <Ue><UeNr UeLe="Gruß" UeFa="Che" UeGr="CHE1">455</UeNr></Ue>
        <Ue><UeNr UeLe="Kra" UeFa="Che" UeGr="che1">474</UeNr></Ue>
        <Ue><UeNr UeLe="Muns" UeFa="Mat" UeGr="MAT1">453</UeNr></Ue>
        <Ue><UeNr UeLe="SchJ" UeFa="Mat" UeGr="mat1">473</UeNr></Ue>
        <Ue><UeNr UeLe="Niem" UeFa="Eng" UeGr="ENG1">461</UeNr></Ue>
        <Ue><UeNr UeLe="Kiss" UeFa="Eng" UeGr="eng1">486</UeNr></Ue>
        <Ue><UeNr UeLe="Got" UeFa="Deu" UeGr="DEU1">490</UeNr></Ue>
        <Ue><UeNr UeLe="Ilgst" UeFa="Deu" UeGr="deu1">491</UeNr></Ue>
      </Unterricht>
      <Pl>
        <Std><St>1</St><Beginn>07:15</Beginn><Ende>08:00</Ende><Fa>CHE1</Fa><Ku2>CHE1</Ku2><Le>Gruß</Le><Ra>243</Ra><Nr>455</Nr><If/></Std>
        <Std><St>2</St><Beginn>08:00</Beginn><Ende>08:45</Ende><Fa>che1</Fa><Ku2>che1</Ku2><Le>Kra</Le><Ra>241</Ra><Nr>474</Nr><If/></Std>
        <Std><St>3</St><Beginn>09:05</Beginn><Ende>09:50</Ende><Fa>MAT1</Fa><Ku2>MAT1</Ku2><Le>Muns</Le><Ra>114</Ra><Nr>453</Nr><If/></Std>
        <Std><St>4</St><Beginn>09:50</Beginn><Ende>10:35</Ende><Fa>mat1</Fa><Ku2>mat1</Ku2><Le>SchJ</Le><Ra>114</Ra><Nr>473</Nr><If/></Std>
        <Std><St>5</St><Beginn>11:00</Beginn><Ende>11:45</Ende><Fa>ENG1</Fa><Ku2>ENG1</Ku2><Le>Niem</Le><Ra>027</Ra><Nr>461</Nr><If/></Std>
        <Std><St>6</St><Beginn>11:45</Beginn><Ende>12:30</Ende><Fa>eng1</Fa><Ku2>eng1</Ku2><Le>Kiss</Le><Ra>027</Ra><Nr>486</Nr><If/></Std>
        <Std><St>7</St><Beginn>12:55</Beginn><Ende>13:40</Ende><Fa>DEU1</Fa><Ku2>DEU1</Ku2><Le>Got</Le><Ra>024</Ra><Nr>490</Nr><If/></Std>
        <Std><St>8</St><Beginn>13:40</Beginn><Ende>14:25</Ende><Fa>deu1</Fa><Ku2>deu1</Ku2><Le>Ilgst</Le><Ra>117</Ra><Nr>491</Nr><If/></Std>
      </Pl>
      <Klausur><KlKurs>CHE1</KlKurs><KlBeginn>09:05</KlBeginn><KlDauer>90</KlDauer><KlInfo>Raum 243</KlInfo></Klausur>
    </Kl>
    <Kl>
      <Kurz>12/1</Kurz>
      <Unterricht>
        <Ue><UeNr UeLe="Drei" UeFa="Bio" UeGr="BIO4">601</UeNr></Ue>
        <Ue><UeNr UeLe="Kiss" UeFa="Eng" UeGr="eng1">602</UeNr></Ue>
      </Unterricht>
      <Pl>
        <Std><St>1</St><Beginn>07:15</Beginn><Ende>08:00</Ende><Fa>Bio</Fa><Ku2>BIO4</Ku2><Le>Drei</Le><Ra>248</Ra><Nr>601</Nr><If/></Std>
        <Std><St>3</St><Beginn>09:05</Beginn><Ende>09:50</Ende><Fa>Eng</Fa><Ku2>eng1</Ku2><Le>Kiss</Le><Ra>027</Ra><Nr>602</Nr><If/></Std>
      </Pl>
    </Kl>
  </Klassen>
  <ZiZeile>Bitte Hinweise im Plan beachten.</ZiZeile>
</VpMobil>
""".encode()


def changed_8g_xml(
    *,
    info: str,
    teacher: str = "BeKe",
    teacher_changed: bool = False,
    room: str = "139",
    room_changed: bool = False,
) -> bytes:
    payload = xml_fixture(info=info)
    payload = payload.replace(
        b'<Fa FaAe="FaGeaendert">---</Fa>', b"<Fa>Eth</Fa>"
    )
    teacher_node = (
        f'<Le LeAe="LeGeaendert">{teacher}</Le>'
        if teacher_changed
        else f"<Le>{teacher}</Le>"
    ).encode()
    room_node = (
        f'<Ra RaAe="RaGeaendert">{room}</Ra>'
        if room_changed
        else f"<Ra>{room}</Ra>"
    ).encode()
    return payload.replace(
        b'<Le LeAe="LeGeaendert"/>', teacher_node
    ).replace(b'<Ra RaAe="RaGeaendert"/>', room_node)


def test_real_friday_8g_cancellation_is_one_block() -> None:
    plan = parse_profile_plan(xml_fixture(), profile_8g())
    assert len(plan.events) == 1
    event = plan.events[0]
    assert event.kind is EventKind.CANCELLATION
    assert event.course == "8eth7"
    assert (event.start_period, event.end_period) == (1, 2)
    assert (event.start_time, event.end_time) == ("07:15", "08:45")
    assert event.info == "8eth7 Frau Becker fällt aus"
    assert event.original_teacher == "BeKe"


@pytest.mark.parametrize(
    ("payload", "kind"),
    [
        (changed_8g_xml(info="Selbststudium"), EventKind.SELF_STUDY),
        (changed_8g_xml(info="Verlegt in die 5. Stunde"), EventKind.MOVED),
        (
            changed_8g_xml(
                info="Frau Vert übernimmt",
                teacher="Vert",
                teacher_changed=True,
            ),
            EventKind.SUBSTITUTION,
        ),
        (
            changed_8g_xml(info="", room="140", room_changed=True),
            EventKind.ROOM_CHANGE,
        ),
        (changed_8g_xml(info="Arbeitsblatt mitbringen"), EventKind.NOTE),
    ],
)
def test_event_kinds(payload: bytes, kind: EventKind) -> None:
    events = parse_profile_plan(payload, profile_8g()).events
    assert len(events) == 1
    assert events[0].kind is kind


def test_course_matching_is_case_and_teacher_sensitive() -> None:
    plan = parse_profile_plan(xml_fixture(), profile_upper())
    assert [(block.course, block.original_teacher) for block in plan.blocks] == [
        ("CHE1", "Gruß"),
        ("MAT1", "Muns"),
        ("eng1", "Kiss"),
        ("DEU1", "Got"),
    ]
    assert plan.general_notes == ("Bitte Hinweise im Plan beachten.",)
    assert plan.exams == ("CHE1 · 09:05 · 90 Min. · Raum 243",)


def test_next_school_days_skips_weekend_and_free_day() -> None:
    result = next_school_days(
        dt.date(2026, 8, 28), 4, {dt.date(2026, 8, 31)}
    )
    assert result == [
        dt.date(2026, 8, 28),
        dt.date(2026, 9, 1),
        dt.date(2026, 9, 2),
        dt.date(2026, 9, 3),
    ]


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        (dt.datetime(2026, 8, 26, 6, 29, tzinfo=BERLIN), False),
        (dt.datetime(2026, 8, 26, 6, 30, tzinfo=BERLIN), True),
        (dt.datetime(2026, 8, 26, 14, 59, tzinfo=BERLIN), True),
        (dt.datetime(2026, 8, 26, 15, 0, tzinfo=BERLIN), False),
        (dt.datetime(2026, 8, 29, 8, 0, tzinfo=BERLIN), False),
    ],
)
def test_active_window_boundaries(when: dt.datetime, expected: bool) -> None:
    assert is_active_window(when, dt.time(6, 30), dt.time(15, 0)) is expected


def test_diff_reports_new_update_and_resolution() -> None:
    original = parse_profile_plan(xml_fixture(), profile_8g()).events[0]
    changed = parse_profile_plan(
        xml_fixture(info="8eth7 fällt aus; Aufgaben in Moodle"), profile_8g()
    ).events[0]
    assert diff_events({}, {original.key: original}) == [Delivery("new", original)]
    assert diff_events({original.key: original}, {changed.key: changed}) == [
        Delivery("updated", changed)
    ]
    assert diff_events({original.key: original}, {}) == [
        Delivery("resolved", original)
    ]


def test_plan_timestamp_alone_does_not_repeat_an_event() -> None:
    original = parse_profile_plan(xml_fixture(), profile_8g()).events[0]
    republished = parse_profile_plan(
        xml_fixture().replace(b"26.08.2026, 06:27", b"26.08.2026, 07:31"),
        profile_8g(),
    ).events[0]
    assert original.plan_timestamp != republished.plan_timestamp
    assert diff_events(
        {original.key: original}, {republished.key: republished}
    ) == []


def test_state_store_roundtrip(tmp_path) -> None:
    event = parse_profile_plan(xml_fixture(), profile_8g()).events[0]
    state = MonitorState(
        initialized=True,
        delivered={event.key: event},
        daily_overviews={"20260828": {"8g"}},
    )
    store = StateStore(tmp_path / "state.json")
    store.save(state)
    loaded = store.load()
    assert loaded == state
    assert json.loads((tmp_path / "state.json").read_text())["initialized"] is True


def test_notification_specs_include_notes_and_split() -> None:
    event = parse_profile_plan(xml_fixture(), profile_8g()).events[0]
    specs = build_notification_specs([Delivery("new", event)] * 30)
    assert len(specs) == 30
    assert specs[0].title == "🚨 Ausfall · 8G"
    assert specs[0].description == (
        "Freitag, 28.08.2026\n\n"
        "❌ 1. Block: 8eth7 – Frau Becker fällt aus"
    )
    assert specs[0].fields == ()


def test_notification_specs_respect_discord_character_limits() -> None:
    event = parse_profile_plan(xml_fixture(info="A" * 9000), profile_8g()).events[0]
    specs = build_notification_specs([Delivery("new", event)])
    assert len(specs) == 1
    for spec in specs:
        total = (
            len(spec.title)
            + len(spec.description)
            + len(spec.footer)
            + sum(len(field.name) + len(field.value) for field in spec.fields)
        )
        assert total <= 6000
        assert all(len(field.name) <= 256 for field in spec.fields)
        assert all(len(field.value) <= 1024 for field in spec.fields)


def test_self_study_push_is_compact() -> None:
    event = parse_profile_plan(
        changed_8g_xml(info="Selbststudium: Aufgaben stehen in Moodle"),
        profile_8g(),
    ).events[0]
    spec = build_notification_specs([Delivery("new", event)])[0]
    assert spec.title == "🚨 Ausfall – Aufgaben stehen in Moodle · 8G"
    assert spec.description.endswith(
        "🧑‍💻 1. Block: 8eth7 – Aufgaben stehen in Moodle"
    )


def test_default_config_contains_all_selected_profiles(tmp_path) -> None:
    config = load_config(
        {
            "VP_USER": "user",
            "VP_PASS": "pass",
            "VP_BASE_URL": "https://example.test/mobdaten",
            "DRY_RUN": "true",
            "STATE_FILE": str(tmp_path / "state.json"),
        }
    )
    profiles = {profile.profile_id: profile for profile in config.profiles}
    assert set(profiles) == {"luca", "jasper", "8g"}
    assert profiles["luca"].source_classes == ("12/2",)
    assert profiles["luca"].label == "Gian · 12/2"
    assert profiles["jasper"].source_classes == ("12/1",)
    assert profiles["jasper"].display_class == "12/2"
    assert CourseRef("CHE1", "Gruß") in profiles["luca"].courses
    assert CourseRef("che1", "Kra") not in profiles["luca"].courses
    assert profiles["8g"].label == "Leni · 8G"
    assert profiles["8g"].daily_overview is True

    parsed = {
        profile_id: parse_profile_plan(xml_fixture(), profile)
        for profile_id, profile in profiles.items()
    }
    assert {block.course for block in parsed["luca"].blocks} == {
        "CHE1",
        "MAT1",
        "eng1",
    }
    assert {block.course for block in parsed["jasper"].blocks} == {
        "BIO4",
        "eng1",
    }
    assert {block.course for block in parsed["8g"].blocks} == {"8eth7"}


class FakeClient:
    def __init__(self) -> None:
        self.version = 1
        self.payload = xml_fixture()
        self.get_plan_calls = 0
        self.fail_plan = False

    def head_file(self, filename: str):
        assert filename == "Klassen.xml"
        return FileFingerprint(etag="catalog")

    def get_file(self, filename: str) -> bytes:
        assert filename == "Klassen.xml"
        return self.payload

    def head_plan(self, day: dt.date):
        if day == dt.date(2026, 8, 28):
            return FileFingerprint(etag=f"plan-{self.version}")
        return None

    def get_plan(self, day: dt.date) -> bytes:
        self.get_plan_calls += 1
        if self.fail_plan:
            raise requests.ConnectionError("temporärer Abruffehler")
        return self.payload


class NoPlanClient(FakeClient):
    def head_plan(self, day: dt.date):
        return None


def service_config(tmp_path) -> AppConfig:
    return AppConfig(
        username="user",
        password="pass",
        base_url="https://example.test/mobdaten",
        discord_token="",
        channel_id=0,
        profiles=(profile_8g(overview=True),),
        check_seconds=60,
        active_start=dt.time(6, 30),
        active_end=dt.time(15, 0),
        overview_time=dt.time(7, 0),
        lookahead_school_days=10,
        timezone=BERLIN,
        state_file=tmp_path / "monitor.json",
        dry_run=True,
    )


def test_service_uses_fingerprints_and_waits_for_ack(tmp_path) -> None:
    client = FakeClient()
    service = MonitorService(service_config(tmp_path), client=client)
    now = dt.datetime(2026, 8, 28, 6, 30, tzinfo=BERLIN)

    first = asyncio.run(service.scan(now, force=True))
    assert first.deliveries == ()
    assert first.fetched_days == (dt.date(2026, 8, 28),)
    assert client.get_plan_calls == 1

    unchanged = asyncio.run(service.scan(now, force=True))
    assert unchanged.fetched_days == ()
    assert unchanged.deliveries == ()
    assert client.get_plan_calls == 1

    client.version = 2
    client.payload = xml_fixture(info="8eth7 fällt aus; Aufgaben in Moodle")
    changed = asyncio.run(service.scan(now, force=True))
    assert [delivery.status for delivery in changed.deliveries] == ["updated"]

    retry = asyncio.run(service.scan(now, force=True))
    assert retry.deliveries == changed.deliveries
    service.acknowledge_deliveries(list(retry.deliveries))
    assert asyncio.run(service.scan(now, force=True)).deliveries == ()


def test_failed_refresh_never_creates_false_resolution(tmp_path) -> None:
    client = FakeClient()
    service = MonitorService(service_config(tmp_path), client=client)
    now = dt.datetime(2026, 8, 28, 7, 30, tzinfo=BERLIN)
    asyncio.run(service.scan(now, force=True))
    assert service.events_for_profile("8g")

    client.version = 2
    client.fail_plan = True
    failed = asyncio.run(service.scan(now, force=True))
    assert failed.deliveries == ()
    assert failed.errors
    assert service.events_for_profile("8g")


def test_overview_is_due_once_after_seven(tmp_path) -> None:
    service = MonitorService(service_config(tmp_path), client=FakeClient())
    before = asyncio.run(
        service.scan(dt.datetime(2026, 8, 28, 6, 59, tzinfo=BERLIN), force=True)
    )
    assert before.overview_profiles == ()

    after = asyncio.run(
        service.scan(dt.datetime(2026, 8, 28, 7, 0, tzinfo=BERLIN), force=True)
    )
    assert after.overview_profiles == ("8g",)
    service.acknowledge_overview(
        "8g", dt.datetime(2026, 8, 28, 7, 0, tzinfo=BERLIN)
    )
    again = asyncio.run(
        service.scan(dt.datetime(2026, 8, 28, 7, 1, tzinfo=BERLIN), force=True)
    )
    assert again.overview_profiles == ()


def test_no_available_plan_never_initializes_or_sends_overview(tmp_path) -> None:
    service = MonitorService(service_config(tmp_path), client=NoPlanClient())
    result = asyncio.run(
        service.scan(dt.datetime(2026, 8, 28, 7, 30, tzinfo=BERLIN), force=True)
    )

    assert service.state.initialized is False
    assert result.overview_profiles == ()
    assert "Keine Plandatei" in result.errors[-1]


def test_source_change_discards_old_delivery_state(tmp_path) -> None:
    config = service_config(tmp_path)
    old_event = parse_profile_plan(xml_fixture(), profile_8g()).events[0]
    StateStore(config.state_file).save(
        MonitorState(
            source_url="https://old.example.test/mobdaten",
            initialized=True,
            observed={old_event.key: old_event},
            delivered={old_event.key: old_event},
            daily_overviews={"20260828": {"8g"}},
        )
    )

    service = MonitorService(config, client=FakeClient())
    result = asyncio.run(
        service.scan(dt.datetime(2026, 8, 28, 7, 30, tzinfo=BERLIN), force=True)
    )

    assert service.state.source_url == config.base_url
    assert service.state.initialized is True
    assert result.deliveries == ()
    assert result.overview_profiles == ("8g",)
