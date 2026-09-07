"""CLI for boot-gated HOUSE day brief reads."""

from __future__ import annotations

import argparse
import json
import os
import sys

from .household_read import (
    HouseholdReadError,
    fetch_day_brief_from_env,
    validate_date,
    validate_timezone,
    validate_viewer,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="household-day-brief",
        description=(
            "Operator-only boot-gated read of a scoped HOUSE day brief. "
            "Requires explicit --live-read for any network I/O."
        ),
    )
    parser.add_argument(
        "--date",
        required=True,
        help="Requested calendar date (ISO YYYY-MM-DD)",
    )
    parser.add_argument(
        "--timezone",
        required=True,
        help="IANA timezone for the requested date",
    )
    parser.add_argument(
        "--viewer",
        default="shared",
        help="Viewer filter (default: shared)",
    )
    parser.add_argument(
        "--live-read",
        action="store_true",
        help="Required to perform network I/O against HOUSE",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if not args.live_read:
            raise HouseholdReadError("live_read_required")
        date_str = validate_date(args.date)
        timezone_str = validate_timezone(args.timezone)
        viewer = validate_viewer(args.viewer)
        result = fetch_day_brief_from_env(
            viewer=viewer,
            date_str=date_str,
            timezone_str=timezone_str,
            env=os.environ,
        )
        print(json.dumps(result, separators=(",", ":"), sort_keys=True))
        return 0
    except KeyboardInterrupt:
        raise
    except HouseholdReadError as exc:
        print(exc.code, file=sys.stderr)
        return 1
    except Exception:
        print(
            json.dumps({"coverage": "unavailable"}, separators=(",", ":")),
            file=sys.stdout,
        )
        print("command_failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
