from __future__ import annotations

import unittest
from typing import Any, Mapping

from household_os.calendar_sync import ProviderWriteResult
from household_os.supabase_store import SupabaseOutboxRepository


OUTBOX_ROW: dict[str, Any] = {
    "event_id": "00000000-0000-0000-0000-000000000001",
    "identity_key": "a" * 64,
    "title": "Lunch — synthetic menu",
    "description": "Synthetic fixture",
    "category_key": "school.lunch",
    "start_date": "2030-09-10",
    "end_date": "2030-09-10",
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


class RecordingRepository(SupabaseOutboxRepository):
    def __init__(self) -> None:
        super().__init__("https://project-demo.supabase.co", "synthetic-secret")
        self.calls: list[tuple[str, str, Mapping[str, Any] | None]] = []

    def _request(
        self, method: str, path: str, body: Mapping[str, Any] | None = None
    ) -> Any:
        self.calls.append((method, path, body))
        if method == "GET":
            return [OUTBOX_ROW]
        return None


class SupabaseRepositoryTests(unittest.TestCase):
    def test_outbox_query_is_bounded_to_target_and_category(self) -> None:
        repository = RecordingRepository()
        items = repository.list_pending(
            target_key="gcal-school-lunch", category_key="school.lunch", limit=5
        )
        self.assertEqual(len(items), 1)
        _, path, _ = repository.calls[0]
        self.assertIn("target_key=eq.gcal-school-lunch", path)
        self.assertIn("category_key=eq.school.lunch", path)
        self.assertIn("limit=5", path)

    def test_success_receipt_uses_atomic_rpc_without_event_content(self) -> None:
        repository = RecordingRepository()
        item = repository.list_pending(
            target_key="gcal-school-lunch", category_key="school.lunch"
        )[0]
        repository.record_success(
            item,
            ProviderWriteResult(
                external_event_id="event-demo",
                provider_version="v1",
                rendering_mode="same_day_2359",
            ),
        )
        method, path, body = repository.calls[-1]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/rest/v1/rpc/record_calendar_delivery_success")
        self.assertEqual(body["p_external_event_id"], "event-demo")  # type: ignore[index]
        self.assertNotIn("title", body)  # type: ignore[operator]
        self.assertNotIn("description", body)  # type: ignore[operator]

    def test_plaintext_supabase_url_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must use https"):
            SupabaseOutboxRepository("http://project-demo.invalid", "synthetic-secret")


if __name__ == "__main__":
    unittest.main()
