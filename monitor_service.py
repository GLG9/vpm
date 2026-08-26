"""Orchestriert Abruf, Zustandsvergleich und Versandquittungen."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import requests

from monitor_config import AppConfig
from monitor_state import (
    Delivery,
    MonitorState,
    StateStore,
    commit_deliveries,
    diff_events,
)
from notification_format import NotificationSpec, build_overview_specs
from vp_10e_plan import (
    PlanClient,
    PlanEvent,
    Profile,
    ProfilePlan,
    is_active_window,
    next_school_days,
    parse_free_days,
    parse_profile_plan,
)

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScanResult:
    deliveries: tuple[Delivery, ...] = ()
    overview_profiles: tuple[str, ...] = ()
    fetched_days: tuple[dt.date, ...] = ()
    errors: tuple[str, ...] = ()


class MonitorService:
    def __init__(
        self,
        config: AppConfig,
        client: PlanClient | None = None,
        store: StateStore | None = None,
    ) -> None:
        self.config = config
        self.client = client or PlanClient(
            config.base_url, config.username, config.password
        )
        self.store = store or StateStore(config.state_file)
        self.state: MonitorState = self.store.load()
        self._lock = asyncio.Lock()

    @property
    def profiles(self) -> dict[str, Profile]:
        return {profile.profile_id: profile for profile in self.config.profiles}

    async def _refresh_catalog(self) -> tuple[bool, str | None]:
        try:
            fingerprint = await asyncio.to_thread(
                self.client.head_file, "Klassen.xml"
            )
            if fingerprint is None:
                return False, "Klassen.xml ist nicht verfügbar"
            if (
                fingerprint != self.state.catalog_fingerprint
                or not self.state.free_days
            ):
                payload = await asyncio.to_thread(
                    self.client.get_file, "Klassen.xml"
                )
                free_days = parse_free_days(payload)
                self.state.free_days = {
                    day.isoformat() for day in free_days
                }
                self.state.catalog_fingerprint = fingerprint
            return True, None
        except (requests.RequestException, ET.ParseError, ValueError) as exc:
            return False, f"Klassen.xml: {exc}"

    def _replace_plan(self, plan: ProfilePlan) -> None:
        prefix = f"{plan.profile.profile_id}:{plan.day:%Y%m%d}:"
        for key in [key for key in self.state.observed if key.startswith(prefix)]:
            del self.state.observed[key]
        for event in plan.events:
            self.state.observed[event.key] = event
        context_key = f"{plan.profile.profile_id}:{plan.day:%Y%m%d}"
        self.state.contexts[context_key] = {
            "notes": list(plan.general_notes),
            "exams": list(plan.exams),
            "timestamp": plan.plan_timestamp,
        }

    def _prune(self, today: dt.date, horizon: set[dt.date]) -> None:
        for mapping in (self.state.observed, self.state.delivered):
            for key, event in list(mapping.items()):
                if event.day < today or event.day not in horizon:
                    del mapping[key]
        valid_dates = {day.strftime("%Y%m%d") for day in horizon}
        for key in list(self.state.fingerprints):
            if key not in valid_dates:
                del self.state.fingerprints[key]
        for key in list(self.state.contexts):
            date_key = key.rsplit(":", 1)[-1]
            if date_key not in valid_dates:
                del self.state.contexts[key]
        cutoff = today - dt.timedelta(days=14)
        for date_key in list(self.state.daily_overviews):
            try:
                day = dt.date(
                    int(date_key[:4]), int(date_key[4:6]), int(date_key[6:8])
                )
            except (ValueError, IndexError):
                del self.state.daily_overviews[date_key]
                continue
            if day < cutoff:
                del self.state.daily_overviews[date_key]

    async def scan(self, now: dt.datetime, *, force: bool = False) -> ScanResult:
        """Prüft alle Zieldateien; Versand wird separat quittiert."""

        async with self._lock:
            local_now = now.astimezone(self.config.timezone) if now.tzinfo else now
            if not force and not is_active_window(
                local_now, self.config.active_start, self.config.active_end
            ):
                return ScanResult()

            catalog_ok, catalog_error = await self._refresh_catalog()
            if not catalog_ok and not self.state.free_days:
                return ScanResult(errors=(catalog_error or "Katalogfehler",))

            free_days = {
                dt.date.fromisoformat(value) for value in self.state.free_days
            }
            days = next_school_days(
                local_now.date(),
                self.config.lookahead_school_days,
                free_days,
            )
            horizon = set(days)
            self._prune(local_now.date(), horizon)

            head_results = await asyncio.gather(
                *(asyncio.to_thread(self.client.head_plan, day) for day in days),
                return_exceptions=True,
            )
            errors: list[str] = []
            if catalog_error:
                errors.append(catalog_error)
            fetched: list[dt.date] = []
            complete = True
            for day, result in zip(days, head_results):
                if isinstance(result, BaseException):
                    complete = False
                    errors.append(f"{day:%Y-%m-%d}: {result}")
                    continue
                if result is None:
                    continue
                date_key = day.strftime("%Y%m%d")
                if self.state.fingerprints.get(date_key) == result:
                    continue
                try:
                    payload = await asyncio.to_thread(self.client.get_plan, day)
                    plans = [
                        parse_profile_plan(payload, profile)
                        for profile in self.config.profiles
                    ]
                except (requests.RequestException, ET.ParseError, ValueError) as exc:
                    complete = False
                    errors.append(f"{day:%Y-%m-%d}: {exc}")
                    continue
                for plan in plans:
                    self._replace_plan(plan)
                self.state.fingerprints[date_key] = result
                fetched.append(day)

            if not self.state.initialized:
                if complete:
                    self.state.delivered = dict(self.state.observed)
                    self.state.initialized = True
                deliveries: list[Delivery] = []
            else:
                deliveries = diff_events(
                    self.state.delivered, self.state.observed
                )
                for key, event in self.state.observed.items():
                    delivered = self.state.delivered.get(key)
                    if delivered and delivered.version == event.version:
                        self.state.delivered[key] = event

            today_key = local_now.strftime("%Y%m%d")
            sent_today = self.state.daily_overviews.get(today_key, set())
            overview_due = local_now.time().replace(tzinfo=None) >= self.config.overview_time
            overview_profiles = tuple(
                profile.profile_id
                for profile in self.config.profiles
                if profile.daily_overview
                and overview_due
                and profile.profile_id not in sent_today
            )
            self.store.save(self.state)
            return ScanResult(
                deliveries=tuple(deliveries),
                overview_profiles=overview_profiles,
                fetched_days=tuple(fetched),
                errors=tuple(errors),
            )

    def events_for_profile(self, profile_id: str) -> list[PlanEvent]:
        return sorted(
            (
                event
                for event in self.state.observed.values()
                if event.profile_id == profile_id
            ),
            key=lambda event: (event.day, event.start_period),
        )

    def overview_specs(self, profile_id: str) -> list[NotificationSpec]:
        profile = self.profiles[profile_id]
        events = self.events_for_profile(profile_id)
        notes: list[str] = []
        exams: list[str] = []
        for key, context in sorted(self.state.contexts.items()):
            if not key.startswith(f"{profile_id}:"):
                continue
            for note in context.get("notes", []):
                if note not in notes:
                    notes.append(note)
            for exam in context.get("exams", []):
                if exam not in exams:
                    exams.append(exam)
        return build_overview_specs(profile, events, notes, exams)

    def acknowledge_deliveries(self, deliveries: list[Delivery]) -> None:
        commit_deliveries(self.state.delivered, deliveries)
        self.store.save(self.state)

    def acknowledge_overview(self, profile_id: str, now: dt.datetime) -> None:
        local_now = now.astimezone(self.config.timezone) if now.tzinfo else now
        key = local_now.strftime("%Y%m%d")
        self.state.daily_overviews.setdefault(key, set()).add(profile_id)
        self.store.save(self.state)

    async def fetch_profile_plan(
        self, day: dt.date, profile_id: str
    ) -> ProfilePlan | None:
        profile = self.profiles.get(profile_id)
        if profile is None:
            return None
        try:
            payload = await asyncio.to_thread(self.client.get_plan, day)
            return parse_profile_plan(payload, profile)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return None
            raise
