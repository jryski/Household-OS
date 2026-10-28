"""Single-host durable travel worker and reference repository.

SQLite is operational staging for the reference runner, not a second HOUSE source
of truth. Production intake must bind to canonical HOUSE identities (see docs).
External notification receivers MUST honor the stable idempotency key.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from dataclasses import replace

from .travel import calendar_item, departure_plan, digest, instant, validate_booking


class TravelRepository:
    def __init__(self, path: str):
        if path != ":memory:":
            # State includes private travel details. Keep it outside source control.
            fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(fd)
            os.chmod(path, 0o600)
        self.db = sqlite3.connect(path, timeout=60, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
          PRAGMA foreign_keys=ON;
          CREATE TABLE IF NOT EXISTS travel_bookings (
            id TEXT PRIMARY KEY, revision INTEGER NOT NULL, hash TEXT NOT NULL,
            payload TEXT NOT NULL, plan TEXT, next_check TEXT,
            calendar_hash TEXT, calendar_target TEXT, last_error TEXT);
          CREATE TABLE IF NOT EXISTS travel_notifications (
            id TEXT PRIMARY KEY, booking_id TEXT NOT NULL REFERENCES travel_bookings(id),
            revision INTEGER NOT NULL, recipient TEXT NOT NULL, kind TEXT NOT NULL,
            payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0, retry_at TEXT, receipt TEXT);
          CREATE INDEX IF NOT EXISTS travel_notification_due ON travel_notifications(state,retry_at);
          CREATE TABLE IF NOT EXISTS travel_overrides (
            booking_id TEXT PRIMARY KEY REFERENCES travel_bookings(id), transfer TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS travel_observations (
            id INTEGER PRIMARY KEY, booking_id TEXT NOT NULL, revision INTEGER NOT NULL,
            hash TEXT NOT NULL, source_ref TEXT NOT NULL, observed_at TEXT NOT NULL);
        """)

    @contextmanager
    def transaction(self):
        # Serialize intake/replanning/delivery on one host. A stale revision cannot
        # deliver while another worker is committing its replacement.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def ingest(self, raw: dict, now: datetime) -> str:
        b = validate_booking(raw)
        key = digest([b["trip_id"], b["booking_id"]])
        content_hash = digest(b)
        with self.transaction():
            old = self.db.execute("SELECT * FROM travel_bookings WHERE id=?", (key,)).fetchone()
            if old and b["revision"] < old["revision"]:
                return "stale"
            if old and b["revision"] == old["revision"]:
                if old["hash"] != content_hash:
                    raise ValueError("same revision has conflicting content; review required")
                return "duplicate"
            self.db.execute("""INSERT INTO travel_bookings(id,revision,hash,payload)
                VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,
                hash=excluded.hash,payload=excluded.payload,plan=NULL,next_check=NULL,last_error=NULL""",
                            (key, b["revision"], content_hash, json.dumps(b)))
            self.db.execute("UPDATE travel_notifications SET state='superseded' WHERE booking_id=? AND state='pending'", (key,))
            self.db.execute("INSERT INTO travel_observations(booking_id,revision,hash,source_ref,observed_at) VALUES(?,?,?,?,?)",
                            (key, b["revision"], content_hash, b["evidence_ref"], now.isoformat()))
        return "updated" if old else "created"

    def configure_transfer(self, booking_id: str, transfer: dict):
        """Keep human origin/mode/buffer choices independent of source revisions."""
        with self.transaction():
            row = self.db.execute("SELECT payload FROM travel_bookings WHERE id=?", (booking_id,)).fetchone()
            if row is None:
                raise ValueError("unknown booking")
            b = json.loads(row["payload"])
            b["transfer"] = transfer
            validate_booking(b)
            self.db.execute("INSERT INTO travel_overrides VALUES(?,?) ON CONFLICT(booking_id) DO UPDATE SET transfer=excluded.transfer",
                            (booking_id, json.dumps(transfer)))
            self.db.execute("UPDATE travel_bookings SET next_check=NULL WHERE id=?", (booking_id,))
            self.db.execute("UPDATE travel_notifications SET state='superseded' WHERE booking_id=? AND state='pending'", (booking_id,))

    def close(self):
        self.db.close()


class TravelWorker:
    """Bounded tick, suitable for a supervisor timer. No background thread promises."""
    def __init__(self, repository: TravelRepository, *, route=None, notify=None,
                 calendar=None, target=None, calendar_ref=None, recipients=(), canonical=None):
        self.repo, self.route, self.notify = repository, route, notify
        self.calendar, self.target, self.calendar_ref = calendar, target, calendar_ref
        self.recipients = frozenset(recipients)
        self.canonical = canonical
        if calendar and (not target or not calendar_ref):
            raise ValueError("calendar requires a fixed configured target and calendar reference")

    def _enqueue(self, key, b, kind, payload):
        for recipient in b["transfer"]["recipients"]:
            if recipient not in self.recipients:
                raise ValueError("recipient is not enrolled in worker configuration")
            # One stage per booking revision; traffic changes key by material plan.
            material = [key, b["revision"], recipient, kind]
            if kind == "changed":
                material.append(payload["leave_by"])
            # A stage already acknowledged for this revision does not repeat at
            # every traffic poll. Pending obsolete plans are replaced below.
            if kind != "changed" and self.repo.db.execute(
                    "SELECT 1 FROM travel_notifications WHERE booking_id=? AND revision=? AND recipient=? AND kind=? AND state='delivered'",
                    (key, b["revision"], recipient, kind)).fetchone():
                continue
            material.append([payload["leave_by"], payload["mode"], payload["quality"]])
            notification_id = digest(material)
            self.repo.db.execute("""INSERT OR IGNORE INTO travel_notifications
                (id,booking_id,revision,recipient,kind,payload) VALUES(?,?,?,?,?,?)""",
                                 (notification_id, key, b["revision"], recipient, kind, json.dumps(payload)))

    def tick(self, now: datetime, *, limit: int = 100) -> dict:
        if now.tzinfo is None or not 1 <= limit <= 1000:
            raise ValueError("aware clock and limit 1..1000 required")
        now = instant(now.isoformat())
        summary = {"checked": 0, "calendar_written": 0, "notified": 0, "failed": 0, "unavailable": []}
        if not self.route:
            summary["unavailable"].append("traffic")
        if not self.notify:
            summary["unavailable"].append("notifications")
        if not self.calendar:
            summary["unavailable"].append("calendar")
        # Holding the local write lock across bounded external calls is deliberate.
        # Multi-host production uses canonical revisions and fenced leases instead.
        with self.repo.transaction():
            rows = self.repo.db.execute("""SELECT * FROM travel_bookings
                WHERE next_check IS NULL OR next_check<=? ORDER BY next_check,id LIMIT ?""",
                                       (now.isoformat(), limit)).fetchall()
            for row in rows:
                b, key = json.loads(row["payload"]), row["id"]
                summary["checked"] += 1
                errors = []
                canonical_id = None
                if self.canonical:
                    try:
                        canonical_id = self.canonical.publish(b)
                    except Exception:
                        summary["failed"] += 1
                        self.repo.db.execute("UPDATE travel_bookings SET next_check=?,last_error=? WHERE id=?",
                                             ((now + timedelta(minutes=5)).isoformat(), "canonical_conflict_or_delivery_failed", key))
                        self.repo.db.execute("UPDATE travel_notifications SET state='superseded' WHERE booking_id=? AND state='pending'", (key,))
                        continue
                if self.calendar:
                    binding = digest([self.target, self.calendar_ref])
                    if row["calendar_target"] and row["calendar_target"] != binding:
                        # Avoid leaving orphan events when a target binding changes.
                        errors.append("calendar_target_changed_requires_review")
                    elif row["calendar_hash"] != row["hash"]:
                        try:
                            item = calendar_item(b, self.target, self.calendar_ref)
                            if canonical_id:
                                item = replace(item, event_id=canonical_id, identity_key=digest(["household-os-travel", b["trip_id"], b["booking_id"]]), category_key=self.canonical.category)
                            if b["status"] == "cancelled":
                                self.calendar.delete(item)
                            else:
                                self.calendar.upsert(item)
                            self.repo.db.execute("UPDATE travel_bookings SET calendar_hash=?,calendar_target=? WHERE id=?",
                                                 (row["hash"], binding, key))
                            summary["calendar_written"] += 1
                        except Exception:
                            errors.append("calendar_delivery_failed")
                override = self.repo.db.execute("SELECT transfer FROM travel_overrides WHERE booking_id=?", (key,)).fetchone()
                if override:
                    b["transfer"] = json.loads(override["transfer"])
                old = json.loads(row["plan"]) if row["plan"] else None
                if b["status"] == "confirmed" and b.get("transfer"):
                    try:
                        plan = departure_plan(b, now, self.route, old)
                        if any(r not in self.recipients for r in b["transfer"]["recipients"]):
                            raise ValueError("unenrolled recipient")
                        leave = instant(plan["leave_by"])
                        # Replanning invalidates queued advice whose time/mode has
                        # changed even when the source booking revision did not.
                        for pending in self.repo.db.execute("SELECT id,payload FROM travel_notifications WHERE booking_id=? AND state='pending'", (key,)).fetchall():
                            queued = json.loads(pending["payload"])
                            if any(queued[k] != plan[k] for k in ("leave_by", "mode", "quality")):
                                self.repo.db.execute("UPDATE travel_notifications SET state='superseded' WHERE id=?", (pending["id"],))
                        # Stop at the required hub arrival deadline; do not deliver
                        # an hours-late 'leave now' message for a departed service.
                        if now <= instant(plan["arrive_by"]):
                            remaining = (leave - now).total_seconds()
                            stage = "leave_now" if remaining <= 0 else "prepare" if remaining <= 3600 else "brief" if remaining <= 86400 else None
                            if stage:
                                self.repo.db.execute("""UPDATE travel_notifications SET state='superseded'
                                  WHERE booking_id=? AND revision=? AND state='pending' AND kind IN ('brief','prepare','changed') AND kind<>?""",
                                                     (key, b["revision"], stage))
                                self._enqueue(key, b, stage, plan)
                            # Notify when cumulative advance since last change >=10m.
                            baseline = (old or {}).get("notified_leave_by", (old or {}).get("leave_by"))
                            if baseline and (instant(baseline) - leave).total_seconds() >= 600 and remaining > 0 and remaining <= 86400:
                                self._enqueue(key, b, "changed", plan)
                                plan["notified_leave_by"] = plan["leave_by"]
                            else:
                                plan["notified_leave_by"] = baseline or plan["leave_by"]
                        self.repo.db.execute("UPDATE travel_bookings SET plan=? WHERE id=?", (json.dumps(plan), key))
                    except Exception:
                        errors.append("departure_plan_or_recipient_invalid")
                if errors:
                    summary["failed"] += 1
                self.repo.db.execute("UPDATE travel_bookings SET next_check=?,last_error=? WHERE id=?",
                                     ((now + timedelta(minutes=5)).isoformat(), ",".join(errors) or None, key))
            if self.notify:
                pending = self.repo.db.execute("""SELECT n.* FROM travel_notifications n
                    JOIN travel_bookings b ON b.id=n.booking_id AND b.revision=n.revision
                    WHERE n.state='pending' AND (n.retry_at IS NULL OR n.retry_at<=?)
                    ORDER BY n.id LIMIT ?""", (now.isoformat(), limit)).fetchall()
                for job in pending:
                    payload = json.loads(job["payload"])
                    if now > instant(payload["arrive_by"]):
                        self.repo.db.execute("UPDATE travel_notifications SET state='expired' WHERE id=?", (job["id"],))
                        continue
                    try:
                        if job["recipient"] not in self.recipients:
                            raise ValueError("recipient revoked")
                        receipt = self.notify(job["recipient"], job["kind"], payload, job["id"])
                        if not isinstance(receipt, str) or not receipt:
                            raise ValueError("notification receiver did not acknowledge delivery")
                        self.repo.db.execute("UPDATE travel_notifications SET state='delivered',receipt=?,attempts=attempts+1 WHERE id=?", (receipt, job["id"]))
                        summary["notified"] += 1
                    except Exception:
                        attempt = job["attempts"] + 1
                        self.repo.db.execute("UPDATE travel_notifications SET attempts=?,retry_at=? WHERE id=?",
                                             (attempt, (now + timedelta(minutes=min(60, 2 ** min(attempt, 6)))).isoformat(), job["id"]))
                        summary["failed"] += 1
        return summary
