"""Validated travel intake, calendar projection, and backward departure planning.

Inputs are structured observations, not agent instructions. No provider access here.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .calendar_sync import DeliveryItem

UTC = timezone.utc


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def instant(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timestamp requires explicit UTC offset")
    return result.astimezone(UTC)


def text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError(f"{name} must be nonempty text of at most 2000 characters")
    return value


def minutes(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite nonnegative number")
    return float(value)


def zoned(value: str, zone: str) -> datetime:
    """Reject nonexistent local times and offsets inconsistent with named zone."""
    supplied = datetime.fromisoformat(value.replace("Z", "+00:00"))
    actual = instant(value).astimezone(ZoneInfo(zone))
    if supplied.replace(tzinfo=None) != actual.replace(tzinfo=None) or supplied.utcoffset() != actual.utcoffset():
        raise ValueError("timestamp offset/local time does not match named timezone")
    return actual


def validate_booking(raw: dict) -> dict:
    b = json.loads(json.dumps(raw, allow_nan=False))
    for key in ("trip_id", "booking_id", "title", "evidence_ref", "timezone", "location"):
        text(b.get(key), key)
    ZoneInfo(b["timezone"])
    if type(b.get("revision")) is not int or b["revision"] < 1:
        raise ValueError("revision must be a positive integer")
    if b.get("kind") not in ("flight", "train", "hotel"):
        raise ValueError("unsupported booking kind")
    if b.get("status", "confirmed") not in ("confirmed", "cancelled"):
        raise ValueError("unsupported status")
    b.setdefault("status", "confirmed")
    if b["kind"] == "hotel":
        start, end = date.fromisoformat(b["start"]), date.fromisoformat(b["end"])
        if end <= start:
            raise ValueError("hotel checkout must follow check-in date")
    else:
        start = zoned(b["start"], b["timezone"])
        end = zoned(b["end"], b.get("arrival_timezone", b["timezone"]))
        if end.astimezone(UTC) <= start.astimezone(UTC):
            raise ValueError("arrival must follow departure")
    t = b.get("transfer")
    if t is not None:
        for field in ("origin", "destination", "mode"):
            text(t.get(field), field)
        # Defaults never invent an airport arrival buffer or an origin.
        if "arrive_by" in t:
            deadline = instant(t["arrive_by"])
        elif b["kind"] != "hotel":
            deadline = instant(b["start"]) - timedelta(minutes=minutes(t["arrival_buffer_minutes"], "arrival buffer"))
        else:
            raise ValueError("hotel transfer requires explicit arrive_by")
        if b["kind"] != "hotel" and deadline > instant(b["start"]):
            raise ValueError("hub arrival deadline follows departure")
        if t.get("cutoff_at"):
            cutoff = instant(t["cutoff_at"])
            if b["kind"] != "hotel" and cutoff > instant(b["start"]):
                raise ValueError("cutoff follows departure")
        minutes(t["fallback_minutes"], "fallback duration")
        for field in ("pickup_minutes", "parking_minutes", "walking_minutes", "contingency_minutes"):
            minutes(t.get(field, 0), field)
        if t.get("origin_timezone"):
            ZoneInfo(t["origin_timezone"])
        if t.get("transport_options"):
            compare_options(t["transport_options"], datetime.now(UTC), **t.get("party", {}))
        recipients = t.get("recipients")
        if not isinstance(recipients, list) or not recipients or len(recipients) != len(set(recipients)):
            raise ValueError("transfer requires unique configured recipient keys")
        for recipient in recipients:
            text(recipient, "recipient")
    return b


def calendar_item(b: dict, target: str, calendar: str) -> DeliveryItem:
    """Reuse the calendar reconciler's model, including inclusive all-day end dates."""
    all_day = b["kind"] == "hotel"
    if all_day:
        start, end = date.fromisoformat(b["start"]), date.fromisoformat(b["end"]) - timedelta(days=1)
        start_time = end_time = None
    else:
        start_at = instant(b["start"]).astimezone(ZoneInfo(b["timezone"]))
        end_at = instant(b["end"]).astimezone(ZoneInfo(b["timezone"]))
        start, end = start_at.date(), end_at.date()
        # Explicit offsets preserve DST folds and arrival instants across zones.
        start_time, end_time = start_at.timetz(), end_at.timetz()
    identity = digest([b["trip_id"], b["booking_id"]])
    return DeliveryItem(event_id=identity, identity_key=f"travel:{identity}", title=b["title"],
                        description=None, category_key="travel", start_date=start, end_date=end,
                        start_time=start_time, end_time=end_time, all_day=all_day,
                        timezone=b["timezone"], location=b["location"], target_key=target,
                        provider="google", external_calendar_ref=calendar, external_event_id=None,
                        canonical_hash=digest(b))


def compare_options(options: list[dict], now: datetime, *, passengers: int = 1,
                    bags: int = 0, child_seats: int = 0) -> list[dict]:
    """Compare supplied observations; no fabricated rideshare pricing or inventory."""
    result = []
    for raw in options:
        o = dict(raw)
        text(o.get("provider"), "provider")
        if o.get("price_kind") not in ("live_quote", "published_fare", "estimate", "unavailable"):
            raise ValueError("price_kind must declare provenance")
        warnings = []
        observed = instant(o["observed_at"])
        age = (now - observed).total_seconds()
        if age < 0 or age > minutes(o.get("max_age_minutes", 15), "quote freshness") * 60:
            warnings.append("stale_or_future_price")
        if o["price_kind"] != "unavailable":
            text(o.get("source_ref"), "price source")
            text(o.get("currency"), "currency")
            o["total_cost"] = sum(minutes(o.get(k, 0), k) for k in
                                  ("price", "fees", "tolls", "parking", "return_price"))
            if "price" not in o:
                raise ValueError("price missing")
        else:
            o["total_cost"] = None
        for required, key in ((passengers, "passenger_capacity"), (bags, "bag_capacity"), (child_seats, "child_seats")):
            if required and key not in o:
                warnings.append(f"{key}_unknown")
            elif required > o.get(key, 0):
                warnings.append(f"{key}_insufficient")
        o["total_minutes"] = sum(minutes(o.get(k, 0), k) for k in
                                 ("travel_minutes", "pickup_minutes", "parking_minutes", "walking_minutes")) if "travel_minutes" in o else None
        if o["total_minutes"] is None:
            warnings.append("travel_time_unavailable")
        o["warnings"] = warnings
        o["comparable"] = not warnings and o["total_cost"] is not None
        result.append(o)
    # No ranking across currencies, freshness or incomplete capacity information.
    return sorted(result, key=lambda o: (not o["comparable"], o.get("currency", ""), o["total_cost"] or 0, o["provider"]))


def departure_plan(b: dict, now: datetime, route: Callable | None = None,
                   previous: dict | None = None) -> dict:
    t = b["transfer"]
    deadline = instant(t["arrive_by"]) if "arrive_by" in t else instant(b["start"]) - timedelta(minutes=t["arrival_buffer_minutes"])
    if t.get("cutoff_at"):
        deadline = min(deadline, instant(t["cutoff_at"]))
    extra = sum(minutes(t.get(k, 0), k) for k in
                ("pickup_minutes", "parking_minutes", "walking_minutes", "contingency_minutes"))
    duration = max(t["fallback_minutes"], (previous or {}).get("travel_minutes", 0))
    source, quality, warning = "configured fallback", "estimate", "routing_unavailable"
    # Query predicted traffic at the intended departure, not at flight takeoff.
    # Retain the longest of bounded refinement samples to avoid oscillation.
    live_durations = []
    if route:
        try:
            for _ in range(3):
                leave = deadline - timedelta(minutes=duration + extra)
                sample = route(t["origin"], t["destination"], max(now, leave), t["mode"])
                age = (now - instant(sample["observed_at"])).total_seconds()
                if not 0 <= age <= 900:
                    raise ValueError("route sample is stale or future dated")
                if sample["origin"] != t["origin"] or sample["destination"] != t["destination"] or sample["mode"] != t["mode"]:
                    raise ValueError("route does not match transfer")
                live_durations.append(minutes(sample["minutes"], "route duration"))
                duration = max(live_durations)
                source = text(sample["source"], "route source")
            quality, warning = "traffic_forecast", None
        except Exception:
            duration = max(duration, t["fallback_minutes"], (previous or {}).get("travel_minutes", 0))
            source, quality, warning = "configured/last-known conservative fallback", "estimate", "routing_unavailable_or_stale"
    leave = deadline - timedelta(minutes=duration + extra)
    local_leave = leave.astimezone(ZoneInfo(t.get("origin_timezone", b["timezone"])))
    message = (f"Leave by {local_leave.strftime('%Y-%m-%d %H:%M %Z')} for {t['destination']}. "
               f"Expected travel: {duration:g} minutes, plus {extra:g} minutes for pickup, parking, walking and contingency. "
               + ("Traffic forecast." if quality == "traffic_forecast" else "Estimate: live routing is unavailable."))
    options = compare_options(t.get("transport_options", []), now, **t.get("party", {}))
    return {"message": message, "origin": t["origin"], "destination": t["destination"], "booking_title": b["title"],
            "transport_options": options, "transport_quotes_available": any(o["comparable"] for o in options),
            "leave_by": leave.isoformat(), "arrive_by": deadline.isoformat(), "travel_minutes": duration,
            "extra_minutes": extra, "mode": t["mode"], "quality": quality, "source": source,
            "warning": warning, "checked_at": now.isoformat(), "late": now > leave}
