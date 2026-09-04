"""Server-side Supabase Data API repository for calendar reconciliation."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .calendar_sync import DeliveryItem, ProviderWriteResult


class SupabaseApiError(RuntimeError):
    pass


class SupabaseOutboxRepository:
    """Read the service-only outbox and atomically record delivery results."""

    def __init__(
        self,
        url: str,
        service_role_key: str,
        *,
        timeout_seconds: int = 30,
    ) -> None:
        if not url.startswith("https://"):
            raise ValueError("HOUSE_SUPABASE_URL must use https")
        if not service_role_key:
            raise ValueError("HOUSE_SUPABASE_SERVICE_ROLE_KEY is required")
        self.base_url = url.rstrip("/")
        self.service_role_key = service_role_key
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None
    ) -> "SupabaseOutboxRepository":
        values = env if env is not None else os.environ
        return cls(
            values.get("HOUSE_SUPABASE_URL", ""),
            values.get("HOUSE_SUPABASE_SERVICE_ROLE_KEY", ""),
        )

    def list_pending(
        self, *, target_key: str, category_key: str, limit: int | None = None
    ) -> Sequence[DeliveryItem]:
        fields = (
            "event_id,identity_key,title,description,category_key,start_date,end_date,"
            "start_time,end_time,all_day,timezone,location,target_key,provider,"
            "external_calendar_ref,external_event_id,canonical_hash"
        )
        params: list[tuple[str, str]] = [
            ("select", fields),
            ("target_key", f"eq.{target_key}"),
            ("category_key", f"eq.{category_key}"),
            ("order", "start_date.asc,title.asc"),
        ]
        if limit is not None:
            if limit < 1:
                raise ValueError("limit must be at least 1")
            params.append(("limit", str(limit)))
        result = self._request(
            "GET", f"/rest/v1/calendar_delivery_outbox?{urlencode(params)}"
        )
        if not isinstance(result, list):
            raise SupabaseApiError("outbox response was not a JSON array")
        return [DeliveryItem.from_mapping(row) for row in result]

    def record_success(self, item: DeliveryItem, result: ProviderWriteResult) -> None:
        self._rpc(
            "record_calendar_delivery_success",
            {
                "p_event_id": item.event_id,
                "p_target_key": item.target_key,
                "p_external_calendar_ref": item.external_calendar_ref,
                "p_external_event_id": result.external_event_id,
                "p_canonical_hash": item.canonical_hash,
                "p_provider_version": result.provider_version,
                "p_rendering_mode": result.rendering_mode,
                "p_synced_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def record_failure(self, item: DeliveryItem, error: str) -> None:
        self._rpc(
            "record_calendar_delivery_failure",
            {
                "p_event_id": item.event_id,
                "p_target_key": item.target_key,
                "p_external_calendar_ref": item.external_calendar_ref,
                "p_canonical_hash": item.canonical_hash,
                "p_error": error[:1000],
            },
        )

    def _rpc(self, function_name: str, body: Mapping[str, Any]) -> Any:
        return self._request("POST", f"/rest/v1/rpc/{function_name}", body)

    def _request(
        self, method: str, path: str, body: Mapping[str, Any] | None = None
    ) -> Any:
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(
            f"{self.base_url}{path}",
            data=payload,
            headers={
                "apikey": self.service_role_key,
                "Authorization": f"Bearer {self.service_role_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            message = "request failed"
            try:
                error_payload = json.loads(exc.read().decode("utf-8"))
                message = str(error_payload.get("message", message))
            except (ValueError, UnicodeDecodeError):
                pass
            raise SupabaseApiError(
                f"Supabase Data API returned HTTP {exc.code}: {message[:500]}"
            ) from exc
        if not raw:
            return None
        return json.loads(raw.decode("utf-8"))
