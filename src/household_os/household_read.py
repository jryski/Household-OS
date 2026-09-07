"""Boot-gated HOUSE day brief reader (stdlib only, operator server-side)."""

from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, OpenerDirector, Request, build_opener
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BOOT_MAX_AGE_SECONDS = 300
BOOT_FUTURE_SKEW_SECONDS = 30
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_RESPONSE_BYTES = 1_048_576
ALLOWED_RPCS = frozenset({"session_boot", "day_brief"})
_REQUIRED_NULLABLE_BRIEF_KEYS = ("school", "lunch", "menu_coverage")


class HouseholdReadError(Exception):
    """Stable operator-facing failure with no upstream detail."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class HouseConfig:
    origin: str
    service_role_key: str = field(repr=False)

    def __post_init__(self) -> None:
        validated_origin = validate_house_origin(self.origin)
        if not self.service_role_key or not self.service_role_key.strip():
            raise HouseholdReadError("config_missing_key")
        object.__setattr__(self, "origin", validated_origin)


def _format_origin(scheme: str, hostname: str, port: int | None) -> str:
    if not scheme or not hostname:
        raise HouseholdReadError("config_invalid_url")
    if port is not None and (port <= 0 or port > 65535):
        raise HouseholdReadError("config_invalid_url")
    if ":" in hostname and not hostname.startswith("["):
        host_repr = f"[{hostname}]"
    else:
        host_repr = hostname
    if port is not None:
        return f"{scheme}://{host_repr}:{port}"
    return f"{scheme}://{host_repr}"


def validate_house_origin(url: str) -> str:
    if not url or url != url.strip():
        raise HouseholdReadError("config_invalid_url")
    if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in url):
        raise HouseholdReadError("config_invalid_url")
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        raise HouseholdReadError("config_invalid_url") from None
    if parsed.scheme != "https":
        raise HouseholdReadError("config_invalid_url")
    if parsed.username or parsed.password:
        raise HouseholdReadError("config_invalid_url")
    if parsed.params:
        raise HouseholdReadError("config_invalid_url")
    if parsed.path and parsed.path not in ("", "/"):
        raise HouseholdReadError("config_invalid_url")
    if "?" in url:
        raise HouseholdReadError("config_invalid_url")
    if "#" in url:
        raise HouseholdReadError("config_invalid_url")
    if not parsed.hostname:
        raise HouseholdReadError("config_invalid_url")
    if any(character in parsed.hostname for character in ("%", "\\")):
        raise HouseholdReadError("config_invalid_url")
    netloc = parsed.netloc
    if "@" in netloc:
        raise HouseholdReadError("config_invalid_url")
    if netloc.endswith(":"):
        raise HouseholdReadError("config_invalid_url")
    if port is None and ":" in netloc:
        host_part = netloc.rsplit("@", 1)[-1]
        if host_part.startswith("[") and "]:" in host_part:
            port_text = host_part.split("]:", 1)[1]
            if port_text and not port_text.isdigit():
                raise HouseholdReadError("config_invalid_url")
        elif not host_part.startswith("[") and host_part.count(":") == 1:
            _, port_text = host_part.rsplit(":", 1)
            if port_text and not port_text.isdigit():
                raise HouseholdReadError("config_invalid_url")
    return _format_origin(parsed.scheme, parsed.hostname, port)


def _validate_positive_int(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise HouseholdReadError("config_invalid_transport")
    if value <= 0:
        raise HouseholdReadError("config_invalid_transport")
    return value


def load_config(env: Mapping[str, str]) -> HouseConfig:
    url = env.get("HOUSE_SUPABASE_URL", "").strip()
    key = env.get("HOUSE_SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url:
        raise HouseholdReadError("config_missing_url")
    if not key:
        raise HouseholdReadError("config_missing_key")
    origin = validate_house_origin(url)
    return HouseConfig(origin=origin, service_role_key=key)


def validate_date(date_str: str) -> str:
    if not date_str:
        raise HouseholdReadError("invalid_date")
    if len(date_str) != 10 or date_str[4] != "-" or date_str[7] != "-":
        raise HouseholdReadError("invalid_date")
    try:
        parsed = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        raise HouseholdReadError("invalid_date")
    if parsed.strftime("%Y-%m-%d") != date_str:
        raise HouseholdReadError("invalid_date")
    return date_str


def validate_timezone(timezone_str: str) -> str:
    if not timezone_str or not timezone_str.strip():
        raise HouseholdReadError("invalid_timezone")
    try:
        ZoneInfo(timezone_str)
    except ZoneInfoNotFoundError:
        raise HouseholdReadError("timezone_unavailable")
    except Exception:
        raise HouseholdReadError("invalid_timezone")
    return timezone_str


def validate_viewer(viewer: str) -> str:
    if not viewer or not viewer.strip():
        raise HouseholdReadError("invalid_viewer")
    return viewer


def rpc_function_name(signature: str) -> str:
    text = signature.strip()
    paren = text.find("(")
    if paren >= 0:
        return text[:paren].strip()
    return text


def _parse_booted_at(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("invalid booted_at type")
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("naive booted_at")
    return parsed


def validate_boot_response(
    payload: Any, viewer: str, now: datetime
) -> None:
    if not isinstance(payload, dict):
        raise HouseholdReadError("boot_malformed")

    if payload.get("viewer") != viewer:
        raise HouseholdReadError("boot_viewer_mismatch")

    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, dict):
        raise HouseholdReadError("boot_malformed")
    rpcs = capabilities.get("rpcs")
    if not isinstance(rpcs, list):
        raise HouseholdReadError("boot_malformed")
    names = [
        rpc_function_name(entry)
        for entry in rpcs
        if isinstance(entry, str)
    ]
    if "day_brief" not in names:
        raise HouseholdReadError("boot_capability_missing")

    if payload.get("instruction_integrity") != "match":
        raise HouseholdReadError("boot_integrity_mismatch")

    health = payload.get("health")
    if not isinstance(health, dict):
        raise HouseholdReadError("boot_malformed")
    drift = health.get("capability_manifest_stale")
    if drift is False or not isinstance(drift, int) or drift != 0:
        raise HouseholdReadError("boot_drift_detected")

    booted_at_raw = payload.get("booted_at")
    try:
        booted_at = _parse_booted_at(booted_at_raw)
    except (TypeError, ValueError):
        raise HouseholdReadError("boot_malformed")

    now_utc = now.astimezone(timezone.utc)
    booted_utc = booted_at.astimezone(timezone.utc)
    age_seconds = (now_utc - booted_utc).total_seconds()
    if age_seconds > BOOT_MAX_AGE_SECONDS:
        raise HouseholdReadError("boot_stale")
    if age_seconds < -BOOT_FUTURE_SKEW_SECONDS:
        raise HouseholdReadError("boot_future")


def validate_and_scope_brief(
    payload: Any, viewer: str, date_str: str
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HouseholdReadError("brief_malformed")

    if payload.get("viewer") != viewer:
        raise HouseholdReadError("brief_viewer_mismatch")
    if payload.get("date") != date_str:
        raise HouseholdReadError("brief_date_mismatch")

    weekday = payload.get("weekday")
    if not isinstance(weekday, str):
        raise HouseholdReadError("brief_malformed")

    for key in _REQUIRED_NULLABLE_BRIEF_KEYS:
        if key not in payload:
            raise HouseholdReadError("brief_malformed")

    school = payload.get("school")
    if school is not None and not isinstance(school, dict):
        raise HouseholdReadError("brief_malformed")

    lunch = payload.get("lunch")
    if lunch is not None and not isinstance(lunch, dict):
        raise HouseholdReadError("brief_malformed")

    events = payload.get("events")
    if not isinstance(events, list):
        raise HouseholdReadError("brief_malformed")
    for event in events:
        if not isinstance(event, dict):
            raise HouseholdReadError("brief_malformed")

    channel_open = payload.get("channel_open")
    if not isinstance(channel_open, list):
        raise HouseholdReadError("brief_malformed")
    for channel in channel_open:
        if not isinstance(channel, dict):
            raise HouseholdReadError("brief_malformed")

    menu_coverage = payload.get("menu_coverage")
    if menu_coverage is not None and not isinstance(menu_coverage, dict):
        raise HouseholdReadError("brief_malformed")

    return {
        "viewer": viewer,
        "date": date_str,
        "weekday": weekday,
        "school": school,
        "lunch": lunch,
        "events": events,
        "channel_open": channel_open,
        "menu_coverage": menu_coverage,
    }


class _RefusingRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        raise HouseholdReadError("redirect_refused")


class HouseRpcTransport:
    """Bounded RPC transport for session_boot and day_brief only."""

    def __init__(
        self,
        config: HouseConfig,
        *,
        opener: OpenerDirector | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        self.config = config
        self.timeout_seconds = _validate_positive_int(timeout_seconds)
        self.max_response_bytes = _validate_positive_int(max_response_bytes)
        if self.timeout_seconds > 120 or self.max_response_bytes > 10_485_760:
            raise HouseholdReadError("config_invalid_transport")
        self._opener = opener or build_opener(_RefusingRedirectHandler())

    def call_rpc(self, function_name: str, body: Mapping[str, Any]) -> Any:
        if function_name not in ALLOWED_RPCS:
            raise HouseholdReadError("rpc_not_allowed")
        path = f"/rest/v1/rpc/{function_name}"
        url = f"{self.config.origin}{path}"
        payload = json.dumps(dict(body)).encode("utf-8")
        request = Request(
            url,
            data=payload,
            headers={
                "apikey": self.config.service_role_key,
                "Authorization": f"Bearer {self.config.service_role_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=self.timeout_seconds) as response:
                final_url = response.geturl()
                if final_url != url:
                    raise HouseholdReadError("redirect_refused")
                raw = response.read(self.max_response_bytes + 1)
        except HouseholdReadError:
            raise
        except HTTPError:
            raise HouseholdReadError("transport_error")
        except (URLError, TimeoutError, socket.timeout):
            raise HouseholdReadError("transport_error")
        except Exception:
            raise HouseholdReadError("transport_error")

        if len(raw) > self.max_response_bytes:
            raise HouseholdReadError("response_too_large")
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise HouseholdReadError("transport_error")


def _bind_transport_config(
    config: HouseConfig, transport: HouseRpcTransport
) -> HouseRpcTransport:
    if (
        transport.config.origin != config.origin
        or transport.config.service_role_key != config.service_role_key
    ):
        raise HouseholdReadError("config_transport_mismatch")
    return transport


def fetch_day_brief(
    config: HouseConfig,
    *,
    viewer: str,
    date_str: str,
    timezone_str: str,
    transport: HouseRpcTransport,
    now: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Run one fresh boot and day_brief on the same transport."""
    viewer = validate_viewer(viewer)
    date_str = validate_date(date_str)
    timezone_str = validate_timezone(timezone_str)
    active_transport = _bind_transport_config(config, transport)
    clock = now or (lambda: datetime.now(timezone.utc))
    boot_payload = active_transport.call_rpc("session_boot", {"p_viewer": viewer})
    validate_boot_response(boot_payload, viewer, clock())
    brief_payload = active_transport.call_rpc(
        "day_brief",
        {
            "p_viewer": viewer,
            "p_date": date_str,
            "p_timezone": timezone_str,
        },
    )
    data = validate_and_scope_brief(brief_payload, viewer, date_str)
    return {
        "coverage": "queried_house_for_requested_date",
        "data": data,
    }


def fetch_day_brief_from_env(
    *,
    viewer: str,
    date_str: str,
    timezone_str: str,
    env: Mapping[str, str] | None = None,
    transport: HouseRpcTransport | None = None,
    now: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    viewer = validate_viewer(viewer)
    date_str = validate_date(date_str)
    timezone_str = validate_timezone(timezone_str)
    values = env if env is not None else os.environ
    config = load_config(values)
    active_transport = transport or HouseRpcTransport(config)
    active_transport = _bind_transport_config(config, active_transport)
    return fetch_day_brief(
        config,
        viewer=viewer,
        date_str=date_str,
        timezone_str=timezone_str,
        transport=active_transport,
        now=now,
    )
