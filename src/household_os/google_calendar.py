"""Minimal Google Calendar API adapter for the HOUSE calendar outbox."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any, Callable, Mapping
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .calendar_sync import (
    DeliveryItem,
    ProviderCapabilities,
    ProviderWriteResult,
)


GOOGLE_CALENDAR_API = "https://www.googleapis.com/calendar/v3"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"


class GoogleApiError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"Google Calendar API returned HTTP {status}: {message[:500]}")
        self.status = status


class GoogleTokenProvider:
    """Load a short-lived access token or refresh one using server-side secrets."""

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self.env = env if env is not None else os.environ
        self._cached_token: str | None = None

    def get_token(self) -> str:
        if self._cached_token:
            return self._cached_token

        direct = self.env.get("HOUSE_GOOGLE_ACCESS_TOKEN")
        if direct:
            self._cached_token = direct
            return direct

        client_id = self.env.get("HOUSE_GOOGLE_CLIENT_ID")
        client_secret = self.env.get("HOUSE_GOOGLE_CLIENT_SECRET")
        refresh_token = self.env.get("HOUSE_GOOGLE_REFRESH_TOKEN")
        if not all((client_id, client_secret, refresh_token)):
            raise RuntimeError(
                "Google credentials are unavailable; provide HOUSE_GOOGLE_ACCESS_TOKEN "
                "or the client ID, client secret, and refresh token"
            )

        payload = urlencode(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }
        ).encode("utf-8")
        request = Request(
            GOOGLE_TOKEN_ENDPOINT,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise GoogleApiError(exc.code, "OAuth token refresh failed") from exc

        token = result.get("access_token")
        if not token:
            raise RuntimeError("Google OAuth response did not contain an access token")
        self._cached_token = str(token)
        return self._cached_token


@dataclass(frozen=True)
class GoogleRenderedEvent:
    external_event_id: str
    rendering_mode: str
    body: dict[str, Any]


def deterministic_google_event_id(item: DeliveryItem) -> str:
    """Return a Calendar-compatible, stable ID for crash-safe event creation."""

    material = f"household-os|{item.target_key}|{item.event_id}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:32]


def render_google_event(
    item: DeliveryItem, capabilities: ProviderCapabilities
) -> GoogleRenderedEvent:
    """Translate canonical date semantics without mutating the HOUSE event."""

    item.validate()
    external_id = item.external_event_id or deterministic_google_event_id(item)
    body: dict[str, Any] = {
        "id": external_id,
        "summary": item.title,
        "visibility": "private",
        "transparency": "transparent",
        "reminders": {"useDefault": False},
        "extendedProperties": {
            "private": {
                "house_event_id": item.event_id,
                "house_identity_key": item.identity_key,
                "house_canonical_hash": item.canonical_hash,
                "house_category_key": item.category_key,
                "house_target_key": item.target_key,
            }
        },
    }
    if item.description:
        body["description"] = item.description
    if item.location:
        body["location"] = item.location

    if item.all_day and capabilities.true_all_day:
        body["start"] = {"date": item.start_date.isoformat()}
        body["end"] = {"date": (item.end_date + timedelta(days=1)).isoformat()}
        mode = "true_all_day"
    elif item.all_day:
        start = datetime.combine(item.start_date, time(0, 0))
        end = datetime.combine(item.end_date, time(23, 59))
        body["start"] = {
            "dateTime": start.isoformat(timespec="seconds"),
            "timeZone": item.timezone,
        }
        body["end"] = {
            "dateTime": end.isoformat(timespec="seconds"),
            "timeZone": item.timezone,
        }
        mode = "same_day_2359"
    else:
        assert item.start_time is not None and item.end_time is not None
        start = datetime.combine(item.start_date, item.start_time)
        end = datetime.combine(item.end_date, item.end_time)
        body["start"] = {
            "dateTime": start.isoformat(timespec="seconds"),
            "timeZone": item.timezone,
        }
        body["end"] = {
            "dateTime": end.isoformat(timespec="seconds"),
            "timeZone": item.timezone,
        }
        mode = "timed"

    return GoogleRenderedEvent(
        external_event_id=external_id, rendering_mode=mode, body=body
    )


Transport = Callable[[str, str, Mapping[str, Any] | None, str], Mapping[str, Any]]


class GoogleCalendarProvider:
    """Idempotent Google Calendar event writer."""

    def __init__(
        self,
        token_provider: GoogleTokenProvider,
        *,
        true_all_day: bool = True,
        transport: Transport | None = None,
    ) -> None:
        self.token_provider = token_provider
        self.capabilities = ProviderCapabilities(true_all_day=true_all_day)
        self._transport = transport or self._http_request

    def upsert(self, item: DeliveryItem) -> ProviderWriteResult:
        rendered = render_google_event(item, self.capabilities)
        calendar_id = quote(item.external_calendar_ref, safe="")
        event_id = quote(rendered.external_event_id, safe="")
        token = self.token_provider.get_token()

        if item.external_event_id:
            result = self._transport(
                "PUT",
                f"/calendars/{calendar_id}/events/{event_id}",
                rendered.body,
                token,
            )
        else:
            try:
                result = self._transport(
                    "POST",
                    f"/calendars/{calendar_id}/events",
                    rendered.body,
                    token,
                )
            except GoogleApiError as exc:
                if exc.status != 409:
                    raise
                result = self._transport(
                    "PUT",
                    f"/calendars/{calendar_id}/events/{event_id}",
                    rendered.body,
                    token,
                )

        returned_id = result.get("id")
        if not returned_id:
            raise RuntimeError("Google Calendar response did not include an event ID")
        version = result.get("etag") or result.get("updated")
        return ProviderWriteResult(
            external_event_id=str(returned_id),
            provider_version=str(version) if version else None,
            rendering_mode=rendered.rendering_mode,
        )

    @staticmethod
    def _http_request(
        method: str,
        path: str,
        body: Mapping[str, Any] | None,
        token: str,
    ) -> Mapping[str, Any]:
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(
            f"{GOOGLE_CALENDAR_API}{path}",
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            message = "request failed"
            try:
                error_payload = json.loads(exc.read().decode("utf-8"))
                message = str(error_payload.get("error", {}).get("message", message))
            except (ValueError, UnicodeDecodeError):
                pass
            raise GoogleApiError(exc.code, message) from exc
