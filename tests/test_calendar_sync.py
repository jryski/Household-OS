from __future__ import annotations

import unittest
from datetime import date, time

from household_os.calendar_sync import (
    CalendarReconciler,
    DeliveryItem,
    ProviderCapabilities,
    ProviderWriteResult,
)
from household_os.google_calendar import (
    GoogleApiError,
    GoogleCalendarProvider,
    deterministic_google_event_id,
    render_google_event,
)


def lunch_event(**overrides: object) -> DeliveryItem:
    values: dict[str, object] = {
        "event_id": "00000000-0000-0000-0000-000000000001",
        "identity_key": "a" * 64,
        "title": "Lunch — synthetic menu",
        "description": "Synthetic fixture",
        "category_key": "school.lunch",
        "start_date": date(2030, 9, 10),
        "end_date": date(2030, 9, 10),
        "start_time": None,
        "end_time": None,
        "all_day": True,
        "timezone": "America/Detroit",
        "location": None,
        "target_key": "gcal-school-lunch",
        "provider": "google",
        "external_calendar_ref": "calendar-demo",
        "external_event_id": None,
        "canonical_hash": "b" * 64,
    }
    values.update(overrides)
    return DeliveryItem(**values)  # type: ignore[arg-type]


class RenderingTests(unittest.TestCase):
    def test_true_all_day_uses_exclusive_provider_end_date(self) -> None:
        rendered = render_google_event(
            lunch_event(), ProviderCapabilities(true_all_day=True)
        )
        self.assertEqual(rendered.rendering_mode, "true_all_day")
        self.assertEqual(rendered.body["start"], {"date": "2030-09-10"})
        self.assertEqual(rendered.body["end"], {"date": "2030-09-11"})
        self.assertEqual(rendered.body["transparency"], "transparent")
        self.assertEqual(rendered.body["visibility"], "private")
        self.assertEqual(rendered.body["reminders"], {"useDefault": False})

    def test_fallback_ends_at_2359_on_same_local_date(self) -> None:
        rendered = render_google_event(
            lunch_event(), ProviderCapabilities(true_all_day=False)
        )
        self.assertEqual(rendered.rendering_mode, "same_day_2359")
        self.assertEqual(
            rendered.body["start"],
            {"dateTime": "2030-09-10T00:00:00", "timeZone": "America/Detroit"},
        )
        self.assertEqual(
            rendered.body["end"],
            {"dateTime": "2030-09-10T23:59:00", "timeZone": "America/Detroit"},
        )

    def test_multiday_fallback_does_not_add_a_display_day(self) -> None:
        rendered = render_google_event(
            lunch_event(end_date=date(2030, 9, 12)),
            ProviderCapabilities(true_all_day=False),
        )
        self.assertEqual(rendered.body["end"]["dateTime"], "2030-09-12T23:59:00")

    def test_missing_timed_end_uses_provider_only_one_hour_default(self) -> None:
        rendered = render_google_event(
            lunch_event(
                category_key="school.pto_meeting",
                target_key="gcal-school-pto-meeting",
                all_day=False,
                start_time=time(18, 0),
                end_time=None,
            ),
            ProviderCapabilities(true_all_day=False),
        )
        self.assertEqual(rendered.rendering_mode, "timed_default_60m")
        self.assertEqual(
            rendered.body["start"],
            {"dateTime": "2030-09-10T18:00:00", "timeZone": "America/Detroit"},
        )
        self.assertEqual(
            rendered.body["end"],
            {"dateTime": "2030-09-10T19:00:00", "timeZone": "America/Detroit"},
        )

    def test_provider_id_is_deterministic_and_calendar_compatible(self) -> None:
        item = lunch_event()
        first = deterministic_google_event_id(item)
        second = deterministic_google_event_id(item)
        self.assertEqual(first, second)
        self.assertRegex(first, r"^[0-9a-f]{32}$")


class _Token:
    def get_token(self) -> str:
        return "synthetic-token"


class GoogleProviderTests(unittest.TestCase):
    def test_conflicting_insert_adopts_deterministic_event_with_update(self) -> None:
        calls: list[tuple[str, str]] = []

        def transport(method: str, path: str, body: object, token: str) -> dict[str, str]:
            calls.append((method, path))
            self.assertEqual(token, "synthetic-token")
            if method == "POST":
                raise GoogleApiError(409, "already exists")
            return {"id": deterministic_google_event_id(lunch_event()), "etag": "v1"}

        provider = GoogleCalendarProvider(_Token(), transport=transport)  # type: ignore[arg-type]
        result = provider.upsert(lunch_event())
        self.assertEqual([method for method, _ in calls], ["POST", "PUT"])
        self.assertEqual(result.provider_version, "v1")
        self.assertEqual(result.rendering_mode, "true_all_day")


class _Repository:
    def __init__(self, items: list[DeliveryItem]) -> None:
        self.items = items
        self.successes: list[tuple[DeliveryItem, ProviderWriteResult]] = []
        self.failures: list[tuple[DeliveryItem, str]] = []

    def list_pending(
        self, *, target_key: str, category_key: str, limit: int | None = None
    ) -> list[DeliveryItem]:
        selected = [
            item
            for item in self.items
            if item.target_key == target_key and item.category_key == category_key
        ]
        return selected[:limit] if limit else selected

    def record_success(self, item: DeliveryItem, result: ProviderWriteResult) -> None:
        self.successes.append((item, result))

    def record_failure(self, item: DeliveryItem, error: str) -> None:
        self.failures.append((item, error))


class _Provider:
    capabilities = ProviderCapabilities()

    def upsert(self, item: DeliveryItem) -> ProviderWriteResult:
        if item.title == "fail":
            raise RuntimeError("synthetic failure")
        return ProviderWriteResult(
            external_event_id=deterministic_google_event_id(item),
            provider_version="v1",
            rendering_mode="true_all_day",
        )


class ReconcilerTests(unittest.TestCase):
    def test_plan_is_read_only(self) -> None:
        repository = _Repository([lunch_event()])
        reconciler = CalendarReconciler(repository, _Provider())
        summary = reconciler.plan(
            target_key="gcal-school-lunch", category_key="school.lunch"
        )
        self.assertEqual(summary.planned, 1)
        self.assertEqual(repository.successes, [])
        self.assertEqual(repository.failures, [])

    def test_failure_is_isolated_and_batch_continues(self) -> None:
        repository = _Repository(
            [
                lunch_event(title="fail"),
                lunch_event(event_id="00000000-0000-0000-0000-000000000002"),
            ]
        )
        reconciler = CalendarReconciler(repository, _Provider())
        summary = reconciler.sync(
            target_key="gcal-school-lunch", category_key="school.lunch"
        )
        self.assertEqual(summary.planned, 2)
        self.assertEqual(summary.created_or_updated, 1)
        self.assertEqual(summary.failed, 1)
        self.assertEqual(len(repository.successes), 1)
        self.assertIn("synthetic failure", repository.failures[0][1])


if __name__ == "__main__":
    unittest.main()
