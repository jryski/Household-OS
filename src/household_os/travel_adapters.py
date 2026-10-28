"""Optional service-side travel adapters. Network access only when called."""
from __future__ import annotations

import json
import math
from datetime import datetime
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen, HTTPRedirectHandler, build_opener

from .google_calendar import GoogleApiError, GoogleCalendarProvider, deterministic_google_event_id
from .travel import UTC


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def post_json(url, body, headers):
    request = Request(url, data=json.dumps(body, allow_nan=False).encode(),
                      headers={"Content-Type": "application/json", **headers}, method="POST")
    with build_opener(NoRedirect()).open(request, timeout=20) as response:
        return json.loads(response.read(1_000_000))


class GoogleTrafficRoutes:
    """Traffic-aware predicted driving duration. API key stays in a header."""
    def __init__(self, api_key, transport=post_json):
        if not api_key:
            raise ValueError("routing API key missing")
        self.api_key, self.transport = api_key, transport

    def __call__(self, origin, destination, depart_at, mode):
        if mode not in ("drive", "taxi", "uber", "lyft"):
            raise ValueError("Google driving adapter cannot estimate this travel mode")
        result = self.transport("https://routes.googleapis.com/directions/v2:computeRoutes", {
            "origin": {"address": origin}, "destination": {"address": destination},
            "travelMode": "DRIVE", "routingPreference": "TRAFFIC_AWARE_OPTIMAL",
            "departureTime": depart_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
        }, {"X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": "routes.duration"})
        duration = result["routes"][0]["duration"]
        if not isinstance(duration, str) or not duration.endswith("s"):
            raise ValueError("invalid routing duration")
        seconds = float(duration[:-1])
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("invalid routing duration")
        return {"minutes": math.ceil(seconds / 60), "observed_at": datetime.now(UTC).isoformat(),
                "origin": origin, "destination": destination, "mode": mode, "source": "Google Routes traffic forecast"}


class NotificationWebhook:
    """Configured receiver maps recipient keys to enrolled notification channels.

    Receiver contract: deduplicate Idempotency-Key and acknowledge with receipt_id.
    No message-controlled URL, bearer token or channel mapping is accepted.
    """
    def __init__(self, url, token, transport=post_json):
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("notification endpoint must be a configured HTTPS URL")
        if not token:
            raise ValueError("notification receiver token missing")
        self.url, self.token, self.transport = url, token, transport

    def __call__(self, recipient, kind, plan, key):
        result = self.transport(self.url, {"recipient_key": recipient, "kind": kind, "plan": plan},
                                {"Authorization": f"Bearer {self.token}", "Idempotency-Key": key})
        if not isinstance(result.get("receipt_id"), str) or not result["receipt_id"]:
            raise ValueError("notification receipt missing")
        return result["receipt_id"]


class TravelGoogleCalendar(GoogleCalendarProvider):
    def delete(self, item):
        calendar = quote(item.external_calendar_ref, safe="")
        event = quote(deterministic_google_event_id(item), safe="")
        try:
            self._transport("DELETE", f"/calendars/{calendar}/events/{event}?sendUpdates=none", None,
                            self.token_provider.get_token())
        except GoogleApiError as exc:
            if exc.status not in (404, 410):
                raise
