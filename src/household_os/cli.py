"""Command-line entry point for the service-side calendar reconciler."""

from __future__ import annotations

import argparse

from .calendar_sync import CalendarReconciler
from .google_calendar import GoogleCalendarProvider, GoogleTokenProvider
from .supabase_store import SupabaseOutboxRepository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="household-calendar-sync",
        description="Plan or reconcile canonical HOUSE calendar deliveries.",
    )
    parser.add_argument("command", choices=("plan", "sync"))
    parser.add_argument("--target", required=True, help="Canonical calendar target key")
    parser.add_argument("--category", required=True, help="Canonical event category key")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--force-same-day-2359",
        action="store_true",
        help="Use 12:00 AM–11:59 PM for canonical all-day events",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Required with sync; confirms external provider writes",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "sync" and not args.live:
        raise SystemExit("sync requires --live; run plan first")

    repository = SupabaseOutboxRepository.from_env()
    provider = GoogleCalendarProvider(
        GoogleTokenProvider(), true_all_day=not args.force_same_day_2359
    )
    reconciler = CalendarReconciler(repository, provider)

    if args.command == "plan":
        summary = reconciler.plan(
            target_key=args.target, category_key=args.category, limit=args.limit
        )
        print(f"planned={summary.planned}")
        return 0

    summary = reconciler.sync(
        target_key=args.target, category_key=args.category, limit=args.limit
    )
    print(
        " ".join(
            (
                f"planned={summary.planned}",
                f"synchronized={summary.created_or_updated}",
                f"failed={summary.failed}",
            )
        )
    )
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
