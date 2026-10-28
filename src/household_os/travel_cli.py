"""Service-side travel runner. Structured imports and private dry-run plans."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from .google_calendar import GoogleTokenProvider
from .travel import UTC, compare_options
from .travel_adapters import GoogleTrafficRoutes, NotificationWebhook, TravelGoogleCalendar
from .travel_runtime import TravelRepository, TravelWorker


def main(argv=None):
    parser = argparse.ArgumentParser(description="Import structured travel observations or run a bounded worker tick.")
    parser.add_argument("command", choices=("ingest", "tick", "status", "compare", "configure-transfer", "poll-inbox"))
    parser.add_argument("--db", default="travel.sqlite", help="Private operational state, outside repository")
    parser.add_argument("--input", help="Validated extraction JSON for ingest or quote observations for compare")
    parser.add_argument("--booking-id", help="Opaque booking key for configure-transfer")
    parser.add_argument("--trip", help="Stable trip identity for iCalendar imports")
    parser.add_argument("--kind", choices=("flight", "train", "hotel"))
    parser.add_argument("--timezone", help="IANA zone for date-only hotel stays")
    parser.add_argument("--evidence", help="Private source reference for iCalendar import")
    parser.add_argument("--live", action="store_true", help="Enable configured network adapters for tick")
    args = parser.parse_args(argv)
    now = datetime.now(UTC)
    if args.command in ("ingest", "compare", "configure-transfer") and not args.input:
        parser.error("--input is required")
    if args.command == "compare":
        raw = json.loads(Path(args.input).read_text())
        print(json.dumps(compare_options(raw["options"], now, **raw.get("party", {}))))
        return 0
    repo = TravelRepository(args.db)
    try:
        if args.command == "poll-inbox":
            if not args.live:
                parser.error("poll-inbox requires --live for configured read-only mailbox access")
            from .travel_mail import GmailCalendarIntake
            tokens = GoogleTokenProvider({"HOUSE_GOOGLE_" + k: v for k, v in
                        (("ACCESS_TOKEN", os.environ.get("HOUSE_TRAVEL_GMAIL_ACCESS_TOKEN")),
                         ("CLIENT_ID", os.environ.get("HOUSE_TRAVEL_GMAIL_CLIENT_ID")),
                         ("CLIENT_SECRET", os.environ.get("HOUSE_TRAVEL_GMAIL_CLIENT_SECRET")),
                         ("REFRESH_TOKEN", os.environ.get("HOUSE_TRAVEL_GMAIL_REFRESH_TOKEN"))) if v})
            result = GmailCalendarIntake(tokens, query=os.environ.get("HOUSE_TRAVEL_GMAIL_QUERY"),
                                        date_timezone=os.environ.get("HOUSE_TRAVEL_DATE_TIMEZONE")).poll(repo, now)
            print(json.dumps(result))
            return 1 if result["review"] or result["failed"] else 0
        if args.command == "configure-transfer":
            if not args.booking_id:
                parser.error("--booking-id is required")
            repo.configure_transfer(args.booking_id, json.loads(Path(args.input).read_text()))
            print(json.dumps({"configured": True}))
            return 0
        if args.command == "ingest":
            if Path(args.input).suffix.lower() == ".ics":
                if not args.trip or not args.evidence:
                    parser.error("iCalendar imports require --trip and --evidence")
                from .travel_intake import parse_ical
                bookings = parse_ical(Path(args.input).read_text(), trip_id=args.trip,
                                      evidence_ref=args.evidence, kind=args.kind, date_timezone=args.timezone)
            else:
                raw = json.loads(Path(args.input).read_text())
                bookings = raw if isinstance(raw, list) else [raw]
            # Validate the complete batch before writing any of it.
            from .travel import validate_booking
            for b in bookings:
                validate_booking(b)
            results = [repo.ingest(b, now) for b in bookings]
            print(json.dumps({"imported": len(results), "results": results}))
            return 0
        if args.command == "status":
            # No itinerary content in operational logs.
            rows = repo.db.execute("SELECT state,count(*) AS count FROM travel_notifications GROUP BY state").fetchall()
            print(json.dumps({"bookings": repo.db.execute("SELECT count(*) FROM travel_bookings").fetchone()[0],
                              "notifications": {r["state"]: r["count"] for r in rows},
                              "bookings_with_errors": repo.db.execute("SELECT count(*) FROM travel_bookings WHERE last_error IS NOT NULL").fetchone()[0]}))
            return 0
        if not args.live:
            # A dry-run must not advance real notification/check state.
            shadow = TravelRepository(":memory:")
            repo.db.backup(shadow.db)
            result = TravelWorker(shadow, recipients=os.environ.get("HOUSE_TRAVEL_RECIPIENTS", "").split(",")).tick(now)
            shadow.close()
            print(json.dumps({"dry_run": True, **result}))
            return 0
        from .travel_house import HouseTravelPublisher
        canonical = HouseTravelPublisher(os.environ.get("HOUSE_SUPABASE_URL", ""),
                    os.environ.get("HOUSE_SUPABASE_SERVICE_ROLE_KEY", ""),
                    owner=os.environ.get("HOUSE_TRAVEL_OWNER"), visibility=os.environ.get("HOUSE_TRAVEL_VISIBILITY"),
                    category=os.environ.get("HOUSE_TRAVEL_CATEGORY"), source_agent=os.environ.get("HOUSE_TRAVEL_SOURCE_AGENT"))
        route = GoogleTrafficRoutes(os.environ["HOUSE_ROUTES_API_KEY"]) if os.environ.get("HOUSE_ROUTES_API_KEY") else None
        notify = NotificationWebhook(os.environ["HOUSE_TRAVEL_NOTIFY_URL"], os.environ.get("HOUSE_TRAVEL_NOTIFY_TOKEN")) if os.environ.get("HOUSE_TRAVEL_NOTIFY_URL") else None
        calendar_ref = os.environ.get("HOUSE_TRAVEL_CALENDAR_REF")
        calendar = TravelGoogleCalendar(GoogleTokenProvider()) if calendar_ref else None
        result = TravelWorker(repo, route=route, notify=notify, calendar=calendar,
                              target=os.environ.get("HOUSE_TRAVEL_TARGET"), calendar_ref=calendar_ref,
                              recipients=[r.strip() for r in os.environ.get("HOUSE_TRAVEL_RECIPIENTS", "").split(",") if r.strip()], canonical=canonical).tick(now)
        print(json.dumps(result))
        return 1 if result["failed"] or result["unavailable"] else 0
    finally:
        repo.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Private booking data or provider response bodies must not reach service logs.
        raise SystemExit(f"travel command failed ({type(exc).__name__}); inspect private input/configuration") from None
