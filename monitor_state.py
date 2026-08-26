"""Persistenter Beobachtungs- und Versandzustand des Monitors."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from vp_10e_plan import FileFingerprint, PlanEvent

DeliveryStatus = Literal["new", "updated", "resolved"]


@dataclass(frozen=True)
class Delivery:
    status: DeliveryStatus
    event: PlanEvent


@dataclass
class MonitorState:
    initialized: bool = False
    catalog_fingerprint: FileFingerprint | None = None
    free_days: set[str] = field(default_factory=set)
    fingerprints: dict[str, FileFingerprint] = field(default_factory=dict)
    observed: dict[str, PlanEvent] = field(default_factory=dict)
    delivered: dict[str, PlanEvent] = field(default_factory=dict)
    contexts: dict[str, dict] = field(default_factory=dict)
    daily_overviews: dict[str, set[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "initialized": self.initialized,
            "catalog_fingerprint": (
                self.catalog_fingerprint.to_dict()
                if self.catalog_fingerprint
                else None
            ),
            "free_days": sorted(self.free_days),
            "fingerprints": {
                key: value.to_dict() for key, value in self.fingerprints.items()
            },
            "observed": {
                key: value.to_dict() for key, value in self.observed.items()
            },
            "delivered": {
                key: value.to_dict() for key, value in self.delivered.items()
            },
            "contexts": self.contexts,
            "daily_overviews": {
                key: sorted(value) for key, value in self.daily_overviews.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> MonitorState:
        catalog = data.get("catalog_fingerprint")
        return cls(
            initialized=bool(data.get("initialized", False)),
            catalog_fingerprint=(
                FileFingerprint.from_dict(catalog) if catalog else None
            ),
            free_days=set(data.get("free_days", [])),
            fingerprints={
                key: FileFingerprint.from_dict(value)
                for key, value in data.get("fingerprints", {}).items()
            },
            observed={
                key: PlanEvent.from_dict(value)
                for key, value in data.get("observed", {}).items()
            },
            delivered={
                key: PlanEvent.from_dict(value)
                for key, value in data.get("delivered", {}).items()
            },
            contexts=dict(data.get("contexts", {})),
            daily_overviews={
                key: set(value)
                for key, value in data.get("daily_overviews", {}).items()
            },
        )


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> MonitorState:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
            return MonitorState()
        try:
            return MonitorState.from_dict(data)
        except (KeyError, TypeError, ValueError):
            return MonitorState()

    def save(self, state: MonitorState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            state.to_dict(), ensure_ascii=False, indent=2, sort_keys=True
        )
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            assert temporary is not None
            os.replace(temporary, self.path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()


def diff_events(
    delivered: Mapping[str, PlanEvent],
    current: Mapping[str, PlanEvent],
) -> list[Delivery]:
    changes: list[Delivery] = []
    for key in sorted(current):
        event = current[key]
        previous = delivered.get(key)
        if previous is None:
            changes.append(Delivery("new", event))
        elif previous.version != event.version:
            changes.append(Delivery("updated", event))
    for key in sorted(set(delivered) - set(current)):
        changes.append(Delivery("resolved", delivered[key]))
    return changes


def commit_deliveries(
    delivered: dict[str, PlanEvent], deliveries: list[Delivery]
) -> None:
    for delivery in deliveries:
        if delivery.status == "resolved":
            delivered.pop(delivery.event.key, None)
        else:
            delivered[delivery.event.key] = delivery.event
