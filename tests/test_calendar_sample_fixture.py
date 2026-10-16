"""Provider-free calendar delivery sample route.

Runs the public reconciliation code end to end over fabricated outbox rows
(tests/fixtures/calendar_sample_outbox.json) with two in-memory doubles, so a
reader can exercise plan, canary, failure isolation, retry, idempotent rerun,
in-place update, crash recovery and input rejection without Supabase, Google
or any credential:

    python -m unittest -v tests.test_calendar_sample_fixture

Doubles:
  * _SampleGoogle implements the transport signature GoogleCalendarProvider
    accepts. A POST for an existing event id returns HTTP 409, which is the
    case the adapter resolves by updating the deterministic event.
  * _SampleOutbox implements the reconciler's repository methods. Its pending
    rule (pending until a success receipt exists for the current canonical
    hash; failed items stay eligible) follows docs/DOGFOOD_CALENDAR_SYNC.md.
    It is a stand-in for the deployment's calendar_delivery_outbox view, not
    a copy of it, so it does not prove the deployed view's behaviour.
"""

from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path

from household_os.calendar_sync import CalendarReconciler, DeliveryItem
from household_os.google_calendar import (
    GoogleApiError,
    GoogleCalendarProvider,
    deterministic_google_event_id,
)

FIXTURE = Path(__file__).with_name("fixtures") / "calendar_sample_outbox.json"
LUNCH = {"target_key": "gcal-school-lunch", "category_key": "school.lunch"}
MEETING = {"target_key": "gcal-school-pto-meeting", "category_key": "school.pto_meeting"}
CALENDAR = "calendar-demo"
TOKEN = "synthetic-token"


def _canonical_hash(row: dict) -> str:
    material = {k: row[k] for k in sorted(row) if k != "canonical_hash"}
    return hashlib.sha256(json.dumps(material, default=str).encode()).hexdigest()


def _sample_rows() -> dict[int, dict]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rows = {}
    for spec in data["rows"]:
        rows[spec["n"]] = _row(spec["n"], data["defaults"], {k: v for k, v in spec.items() if k != "n"})
    return rows


def _row(n: int, defaults: dict | None = None, values: dict | None = None, **over: object) -> dict:
    row = {
        **(defaults or json.loads(FIXTURE.read_text(encoding="utf-8"))["defaults"]),
        "event_id": f"00000000-0000-0000-0000-{n:012d}",
        "identity_key": f"{n:064x}",
        "title": f"Lunch — synthetic menu {n}",
        "start_date": f"2030-09-{9 + n:02d}",
        "end_date": f"2030-09-{9 + n:02d}",
        **LUNCH,
    }
    row.update(values or {})
    row.update(over)
    row.pop("canonical_hash", None)
    row["canonical_hash"] = _canonical_hash(row)
    return row


class _SampleGoogle:
    def __init__(self) -> None:
        self.events: dict[tuple[str, str], dict] = {}
        self.calls: list[str] = []
        self.fail_next_for: set[str] = set()
        self._version = 0

    def __call__(self, method: str, path: str, body: dict, token: str) -> dict:
        if token != TOKEN:
            raise AssertionError("unexpected token")
        self.calls.append(method)
        parts = path.strip("/").split("/")  # calendars/<calendar>/events[/<id>]
        calendar = parts[1]
        event_id = body["id"] if method == "POST" else parts[3]
        if event_id in self.fail_next_for:
            self.fail_next_for.discard(event_id)
            raise GoogleApiError(503, "synthetic backend unavailable")
        if method == "POST" and (calendar, event_id) in self.events:
            raise GoogleApiError(409, "already exists")
        self._version += 1
        self.events[(calendar, event_id)] = {**body, "etag": f'"v{self._version}"'}
        return {"id": event_id, "etag": f'"v{self._version}"'}


class _SampleToken:
    def get_token(self) -> str:
        return TOKEN


class _SampleOutbox:
    def __init__(self, rows: dict[int, dict]) -> None:
        self.rows = {r["event_id"]: r for r in rows.values()}
        self.links: dict[tuple[str, str], dict] = {}
        self.failures: list[str] = []

    def put(self, row: dict) -> None:
        self.rows[row["event_id"]] = row

    def list_pending(self, *, target_key: str, category_key: str, limit: int | None = None):
        pending = []
        for row in sorted(self.rows.values(), key=lambda r: (r["start_date"], r["title"])):
            if row["target_key"] != target_key or row["category_key"] != category_key:
                continue
            link = self.links.get((row["event_id"], target_key))
            if link and link["state"] == "synced" and link["canonical_hash"] == row["canonical_hash"]:
                continue
            external = link.get("external_event_id") if link else None
            pending.append(DeliveryItem.from_mapping(dict(row, external_event_id=external)))
        return pending[:limit] if limit else pending

    def record_success(self, item, result) -> None:
        self.links[(item.event_id, item.target_key)] = {
            "state": "synced",
            "external_event_id": result.external_event_id,
            "canonical_hash": item.canonical_hash,
            "provider_version": result.provider_version,
            "rendering_mode": result.rendering_mode,
        }

    def record_failure(self, item, error: str) -> None:
        self.failures.append(error[:1000])
        prior = self.links.get((item.event_id, item.target_key), {})
        self.links[(item.event_id, item.target_key)] = {**prior, "state": "failed",
                                                        "canonical_hash": prior.get("canonical_hash")}


def _world(**provider_options):
    rows = _sample_rows()
    google, outbox = _SampleGoogle(), _SampleOutbox(rows)
    provider = GoogleCalendarProvider(_SampleToken(), transport=google, **provider_options)
    return rows, google, outbox, provider, CalendarReconciler(outbox, provider)


def _event_id(row: dict) -> str:
    return deterministic_google_event_id(DeliveryItem.from_mapping(row))


def _counts(summary) -> tuple[int, int, int]:
    return summary.planned, summary.created_or_updated, summary.failed


class CalendarSampleRouteTests(unittest.TestCase):
    def test_01_plan_counts_scope_without_provider_calls(self) -> None:
        _, google, _, _, rec = _world()
        self.assertEqual(rec.plan(**LUNCH).planned, 3)
        self.assertEqual(google.calls, [])

    def test_02_canary_creates_one_private_transparent_all_day_event(self) -> None:
        rows, google, outbox, _, rec = _world()
        self.assertEqual(_counts(rec.sync(**LUNCH, limit=1)), (1, 1, 0))
        self.assertEqual(len(google.events), 1)
        event = google.events[(CALENDAR, _event_id(rows[1]))]
        self.assertEqual(event["visibility"], "private")
        self.assertEqual(event["transparency"], "transparent")
        self.assertEqual(event["reminders"], {"useDefault": False})
        self.assertEqual(event["start"], {"date": "2030-09-10"})
        self.assertEqual(event["end"], {"date": "2030-09-11"})  # exclusive end
        link = outbox.links[(rows[1]["event_id"], LUNCH["target_key"])]
        self.assertEqual(link["state"], "synced")
        self.assertEqual(link["external_event_id"], _event_id(rows[1]))
        self.assertEqual(link["canonical_hash"], rows[1]["canonical_hash"])
        self.assertTrue(link["provider_version"])
        self.assertEqual(link["rendering_mode"], "true_all_day")

    def test_03_failure_is_isolated_bounded_and_retried(self) -> None:
        rows, google, outbox, _, rec = _world()
        google.fail_next_for.add(_event_id(rows[3]))
        self.assertEqual(_counts(rec.sync(**LUNCH)), (3, 2, 1))
        self.assertIn("HTTP 503", outbox.failures[-1])
        self.assertLessEqual(len(outbox.failures[-1]), 1000)
        self.assertEqual(rec.plan(**LUNCH).planned, 1)  # still eligible
        self.assertEqual(_counts(rec.sync(**LUNCH)), (1, 1, 0))

    def test_04_rerun_is_idempotent(self) -> None:
        _, google, _, _, rec = _world()
        rec.sync(**LUNCH)
        events, calls = len(google.events), len(google.calls)
        self.assertEqual(_counts(rec.sync(**LUNCH)), (0, 0, 0))
        self.assertEqual((len(google.events), len(google.calls)), (events, calls))

    def test_05_canonical_change_updates_the_same_event(self) -> None:
        rows, google, outbox, _, rec = _world()
        rec.sync(**LUNCH)
        events, calls = len(google.events), len(google.calls)
        changed = _row(2, values={k: v for k, v in rows[2].items() if k != "canonical_hash"},
                       title="Lunch — synthetic menu 2 (corrected)")
        outbox.put(changed)
        self.assertEqual(rec.sync(**LUNCH).created_or_updated, 1)
        self.assertEqual(google.calls[calls:], ["PUT"])
        self.assertEqual(len(google.events), events)
        self.assertTrue(google.events[(CALENDAR, _event_id(changed))]["summary"].endswith("(corrected)"))

    def test_06_lost_receipt_retry_adopts_existing_event(self) -> None:
        _, google, outbox, provider, rec = _world()
        rec.sync(**LUNCH)
        late = _row(5)
        outbox.put(late)
        provider.upsert(DeliveryItem.from_mapping(late))  # provider write whose receipt was lost
        calls = len(google.calls)
        self.assertEqual(rec.sync(**LUNCH).created_or_updated, 1)
        self.assertEqual(google.calls[calls:], ["POST", "PUT"])  # 409, then update
        self.assertEqual(sum(1 for key in google.events if key[1] == _event_id(late)), 1)

    def test_07_start_only_timed_event_gets_provider_only_hour(self) -> None:
        rows, google, outbox, _, rec = _world()
        rec.sync(**MEETING)
        link = outbox.links[(rows[4]["event_id"], MEETING["target_key"])]
        self.assertEqual(link["rendering_mode"], "timed_default_60m")
        self.assertEqual(google.events[(CALENDAR, link["external_event_id"])]["end"]["dateTime"],
                         "2030-09-13T19:00:00")
        self.assertIsNone(outbox.rows[rows[4]["event_id"]]["end_time"])  # canonical end stays empty

    def test_08_connector_without_true_all_day_uses_same_day_fallback(self) -> None:
        _, _, _, provider, _ = _world(true_all_day=False)
        self.assertEqual(provider.upsert(DeliveryItem.from_mapping(_row(6))).rendering_mode, "same_day_2359")

    def test_09_invalid_canonical_inputs_are_rejected(self) -> None:
        cases = {
            "end_before_start": _row(7, end_date="2030-09-01"),
            "all_day_with_times": _row(8, start_time="09:00:00"),
            "timed_without_start": _row(9, all_day=False),
            "unsupported_provider": _row(10, provider="skylight"),
            "missing_required_field": {k: v for k, v in _row(11).items() if k != "canonical_hash"},
            "empty_title": _row(12, title="   "),
        }
        for label, row in cases.items():
            with self.subTest(label), self.assertRaises(ValueError):
                DeliveryItem.from_mapping(row)

    def test_10_summaries_carry_counts_only(self) -> None:
        _, google, outbox, _, rec = _world()
        google.fail_next_for.add(_event_id(_sample_rows()[2]))
        text = json.dumps([rec.plan(**LUNCH).__dict__, rec.sync(**LUNCH).__dict__], default=str)
        self.assertNotIn("synthetic menu", text)
        self.assertNotIn(CALENDAR, text)
        self.assertIsNone(re.search(r"[0-9a-f]{32}", text))


if __name__ == "__main__":
    unittest.main()
