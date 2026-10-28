"""Conservative iCalendar travel attachment intake, using only explicit data.

Supports non-recurring VEVENTs with IANA TZID or UTC and date-only hotel
stays. Unsupported/floating/ambiguous events fail for review instead of guessing.
VTIMEZONE rules are not executed; the installed IANA database is authoritative.
"""
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from .travel import UTC, digest, validate_booking


def unescape(value):
    return re.sub(r"\\([nN,;\\])", lambda m: "\n" if m[1] in "nN" else m[1], value)


def parse_datetime(value, params):
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        return datetime.strptime(value, "%Y%m%d").date().isoformat(), None
    if value.endswith("Z"):
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC).isoformat(), "UTC"
    zone = params.get("TZID")
    if not zone:
        raise ValueError("floating iCalendar time requires review")
    naive = datetime.strptime(value, "%Y%m%dT%H%M%S")
    tz = ZoneInfo(zone)
    first, second = naive.replace(tzinfo=tz, fold=0), naive.replace(tzinfo=tz, fold=1)
    if first.utcoffset() != second.utcoffset():
        raise ValueError("ambiguous/nonexistent iCalendar local time requires review")
    if first.astimezone(UTC).astimezone(tz).replace(tzinfo=None) != naive:
        raise ValueError("nonexistent iCalendar time")
    return first.isoformat(), zone


def parse_ical(content: str, *, trip_id: str, evidence_ref: str, kind: str | None = None,
               date_timezone: str | None = None) -> list[dict]:
    if len(content) > 2_000_000 or "BEGIN:VCALENDAR" not in content:
        raise ValueError("invalid or oversized iCalendar input")
    lines = re.sub(r"\r?\n[ \t]", "", content).splitlines()
    events, fields, stack = [], None, []
    method = "PUBLISH"
    for line in lines:
        if line.startswith("BEGIN:"):
            component = line[6:]
            stack.append(component)
            if component == "VEVENT":
                if fields is not None:
                    raise ValueError("nested event")
                fields = {}
            continue
        if line.startswith("END:"):
            component = line[4:]
            if not stack or stack.pop() != component:
                raise ValueError("unbalanced calendar")
            if component == "VEVENT":
                events.append(fields)
                fields = None
            continue
        if ":" not in line:
            continue
        header, value = line.split(":", 1)
        bits = header.split(";")
        name = bits[0].upper()
        if name == "METHOD" and stack == ["VCALENDAR"]:
            method = value.upper()
        if fields is None or not stack or stack[-1] != "VEVENT":
            continue
        params = {}
        for bit in bits[1:]:
            k, v = bit.split("=", 1)
            params[k.upper()] = v.strip('"')
        if name in fields:
            raise ValueError("duplicate iCalendar property requires review")
        fields[name] = (value, params)
    if stack or fields is not None or not events:
        raise ValueError("incomplete or empty calendar")
    result = []
    for f in events:
        if any(k in f for k in ("RRULE", "RDATE", "EXDATE", "RECURRENCE-ID")):
            raise ValueError("recurring travel event requires review")
        def get(name, default=""):
            return unescape(f.get(name, (default, {}))[0])
        title = get("SUMMARY")
        event_kind = kind
        if event_kind is None:
            matches = [k for k in ("flight", "train", "hotel") if re.search(r"\b" + k + r"\b", title, re.I)]
            if len(matches) != 1:
                raise ValueError("travel kind unclear; provide explicit kind")
            event_kind = matches[0]
        start, start_zone = parse_datetime(*f["DTSTART"])
        end, end_zone = parse_datetime(*f["DTEND"])
        if event_kind == "hotel":
            if bool(start_zone) != bool(end_zone):
                raise ValueError("mixed date and timestamp hotel boundaries")
            start, end = start[:10], end[:10]
        elif not start_zone or not end_zone:
            raise ValueError("transport booking requires exact times")
        zone = start_zone or date_timezone
        if not zone:
            raise ValueError("date-only stay requires configured local timezone")
        # SEQUENCE is preferred. Without one, DTSTAMP provides a monotonic source
        # revision. Equal-revision conflicts remain reviewable in the repository.
        revision = int(get("SEQUENCE")) + 1 if "SEQUENCE" in f else int(datetime.strptime(get("DTSTAMP"), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC).timestamp()) + 1
        b = {"trip_id": trip_id, "booking_id": digest(get("UID")), "revision": revision,
             "kind": event_kind, "title": title, "timezone": zone,
             "start": start, "end": end, "location": get("LOCATION"),
             "status": "cancelled" if get("STATUS").upper() == "CANCELLED" or method == "CANCEL" else "confirmed",
             "evidence_ref": evidence_ref}
        if not get("UID"):
            raise ValueError("event UID missing")
        if event_kind != "hotel":
            b["arrival_timezone"] = end_zone
        # Preserve only recognized itinerary facts, not arbitrary body instructions.
        description = get("DESCRIPTION")
        for label, key in (("Flight Number", "flight_number"), ("Departure Terminal", "departure_terminal"),
                           ("Arrival Terminal", "arrival_terminal"), ("Departure City/Airport", "departure_hub"),
                           ("Arrival City/Airport", "arrival_hub")):
            match = re.search(r"(?:^|\n)" + re.escape(label) + r"\s*:\s*([^\n]+)", description)
            if match and match[1].strip().lower() != "not applicable":
                b[key] = match[1].strip()
        result.append(validate_booking(b))
    return result
