"""Canonical calendar delivery models and reconciliation service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class DeliveryItem:
    """One canonical HOUSE event that should be delivered to one target."""

    event_id: str
    identity_key: str
    title: str
    description: str | None
    category_key: str
    start_date: date
    end_date: date
    start_time: time | None
    end_time: time | None
    all_day: bool
    timezone: str
    location: str | None
    target_key: str
    provider: str
    external_calendar_ref: str
    external_event_id: str | None
    canonical_hash: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "DeliveryItem":
        required = (
            "event_id",
            "identity_key",
            "title",
            "category_key",
            "start_date",
            "end_date",
            "all_day",
            "timezone",
            "target_key",
            "provider",
            "external_calendar_ref",
            "canonical_hash",
        )
        missing = [key for key in required if value.get(key) in (None, "")]
        if missing:
            raise ValueError(f"outbox item is missing required fields: {', '.join(missing)}")

        item = cls(
            event_id=str(value["event_id"]),
            identity_key=str(value["identity_key"]),
            title=str(value["title"]),
            description=_optional_text(value.get("description")),
            category_key=str(value["category_key"]),
            start_date=_parse_date(value["start_date"]),
            end_date=_parse_date(value["end_date"]),
            start_time=_parse_time(value.get("start_time")),
            end_time=_parse_time(value.get("end_time")),
            all_day=bool(value["all_day"]),
            timezone=str(value["timezone"]),
            location=_optional_text(value.get("location")),
            target_key=str(value["target_key"]),
            provider=str(value["provider"]),
            external_calendar_ref=str(value["external_calendar_ref"]),
            external_event_id=_optional_text(value.get("external_event_id")),
            canonical_hash=str(value["canonical_hash"]),
        )
        item.validate()
        return item

    def validate(self) -> None:
        if self.end_date < self.start_date:
            raise ValueError("event end_date precedes start_date")
        if not self.title.strip():
            raise ValueError("event title is empty")
        if self.all_day and (self.start_time is not None or self.end_time is not None):
            raise ValueError("canonical all-day event cannot include times")
        if not self.all_day and self.start_time is None:
            raise ValueError("timed event requires start_time")
        if self.provider != "google":
            raise ValueError(f"unsupported provider: {self.provider}")


@dataclass(frozen=True)
class ProviderCapabilities:
    true_all_day: bool = True


@dataclass(frozen=True)
class ProviderWriteResult:
    external_event_id: str
    provider_version: str | None
    rendering_mode: str


@dataclass(frozen=True)
class SyncSummary:
    planned: int = 0
    created_or_updated: int = 0
    failed: int = 0


class CalendarProvider(Protocol):
    capabilities: ProviderCapabilities

    def upsert(self, item: DeliveryItem) -> ProviderWriteResult:
        """Create or update one provider event idempotently."""


class OutboxRepository(Protocol):
    def list_pending(
        self, *, target_key: str, category_key: str, limit: int | None = None
    ) -> Sequence[DeliveryItem]:
        """Return canonical events requiring provider reconciliation."""

    def record_success(self, item: DeliveryItem, result: ProviderWriteResult) -> None:
        """Persist the provider identity and synchronized canonical hash."""

    def record_failure(self, item: DeliveryItem, error: str) -> None:
        """Persist a bounded failure without losing the pending delivery."""


class CalendarReconciler:
    """Synchronize a bounded outbox selection while isolating per-item failures."""

    def __init__(self, repository: OutboxRepository, provider: CalendarProvider) -> None:
        self.repository = repository
        self.provider = provider

    def plan(
        self, *, target_key: str, category_key: str, limit: int | None = None
    ) -> SyncSummary:
        items = self.repository.list_pending(
            target_key=target_key, category_key=category_key, limit=limit
        )
        return SyncSummary(planned=len(items))

    def sync(
        self, *, target_key: str, category_key: str, limit: int | None = None
    ) -> SyncSummary:
        items = self.repository.list_pending(
            target_key=target_key, category_key=category_key, limit=limit
        )
        succeeded = 0
        failed = 0
        for item in items:
            try:
                result = self.provider.upsert(item)
                self.repository.record_success(item, result)
                succeeded += 1
            except Exception as exc:  # isolate one event from the remaining batch
                self.repository.record_failure(item, _bounded_error(exc))
                failed += 1
        return SyncSummary(
            planned=len(items), created_or_updated=succeeded, failed=failed
        )


def _parse_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _parse_time(value: Any) -> time | None:
    if value in (None, ""):
        return None
    if isinstance(value, time):
        return value
    return time.fromisoformat(str(value))


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _bounded_error(error: Exception) -> str:
    text = f"{type(error).__name__}: {error}".replace("\n", " ").strip()
    return text[:1000]
