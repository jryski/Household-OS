"""Narrow Skylight display-calendar activation adapter.

Skylight is a display target, not a canonical calendar provider. This module
therefore manages only which already-connected provider calendars are active
on a Skylight frame. It does not create, update, or delete events.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, Sequence
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


SKYLIGHT_API = "https://app.ourskylight.com/api"
SKYLIGHT_API_VERSION = "2026-05-01"


class SkylightApiError(RuntimeError):
    """A bounded Skylight API failure that never includes response content."""

    def __init__(self, status: int) -> None:
        super().__init__(f"Skylight API returned HTTP {status}")
        self.status = status


class AccessTokenProvider(Protocol):
    def get_token(self) -> str:
        """Return a server-side bearer token."""


class SkylightAccessTokenProvider:
    """Load a short-lived token without accepting a household password."""

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self.env = env if env is not None else os.environ

    def get_token(self) -> str:
        token = self.env.get("HOUSE_SKYLIGHT_ACCESS_TOKEN", "").strip()
        if not token:
            raise RuntimeError(
                "Skylight access is unavailable; provide a server-side "
                "HOUSE_SKYLIGHT_ACCESS_TOKEN"
            )
        return token


@dataclass(frozen=True)
class DisplayCalendarRoute:
    """One HOUSE-managed provider calendar and its display visibility policy."""

    external_calendar_ref: str
    visible: bool


@dataclass(frozen=True)
class SkylightCalendarAccount:
    """The subset of a connected Skylight calendar account HOUSE needs."""

    account_id: str
    active_calendar_refs: tuple[str, ...]


@dataclass(frozen=True)
class SkylightActivationPlan:
    """A reversible active-calendar update for one connected account."""

    account_id: str
    current_active_refs: tuple[str, ...]
    desired_active_refs: tuple[str, ...]
    added_refs: tuple[str, ...]
    removed_refs: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return self.current_active_refs != self.desired_active_refs


def plan_calendar_activation(
    account: SkylightCalendarAccount,
    routes: Sequence[DisplayCalendarRoute],
) -> SkylightActivationPlan:
    """Apply HOUSE visibility policy while preserving every unmanaged calendar."""

    current = _unique_refs(account.active_calendar_refs)
    normalized_routes = _normalize_routes(routes)
    visibility_by_ref = {
        route.external_calendar_ref: route.visible for route in normalized_routes
    }

    desired = [
        ref
        for ref in current
        if ref not in visibility_by_ref or visibility_by_ref[ref]
    ]
    desired.extend(
        route.external_calendar_ref
        for route in normalized_routes
        if route.visible and route.external_calendar_ref not in desired
    )
    desired_refs = _unique_refs(desired)

    current_set = set(current)
    desired_set = set(desired_refs)
    return SkylightActivationPlan(
        account_id=account.account_id,
        current_active_refs=current,
        desired_active_refs=desired_refs,
        added_refs=tuple(ref for ref in desired_refs if ref not in current_set),
        removed_refs=tuple(ref for ref in current if ref not in desired_set),
    )


Transport = Callable[[str, str, Mapping[str, Any] | None, str], Mapping[str, Any]]


class SkylightCalendarClient:
    """Minimal client for the observed Skylight calendar-account contract."""

    def __init__(
        self,
        token_provider: AccessTokenProvider,
        *,
        base_url: str = SKYLIGHT_API,
        transport: Transport | None = None,
    ) -> None:
        self.token_provider = token_provider
        self.base_url = base_url.rstrip("/")
        self._transport = transport or self._http_request

    def resolve_frame_id(self, explicit_frame_id: str | None = None) -> str:
        if explicit_frame_id:
            return explicit_frame_id
        document = self._request("GET", "/frames")
        resources = _resources(document)
        if len(resources) == 1:
            return str(resources[0]["id"])
        if not resources:
            raise RuntimeError("No Skylight frame is available")
        raise RuntimeError("Multiple Skylight frames are available; select one in setup")

    def list_calendar_accounts(self, frame_id: str) -> tuple[SkylightCalendarAccount, ...]:
        frame_ref = quote(frame_id, safe="")
        document = self._request("GET", f"/frames/{frame_ref}/calendars")
        accounts: list[SkylightCalendarAccount] = []
        for resource in _resources(document):
            attributes = resource.get("attributes")
            attrs = attributes if isinstance(attributes, Mapping) else {}
            active = attrs.get("active_calendars", ())
            active_values = active if isinstance(active, (list, tuple)) else ()
            accounts.append(
                SkylightCalendarAccount(
                    account_id=str(resource["id"]),
                    active_calendar_refs=_unique_refs(active_values),
                )
            )
        return tuple(accounts)

    def update_active_calendars(
        self,
        *,
        frame_id: str,
        account_id: str,
        active_calendar_refs: Sequence[str],
    ) -> None:
        frame_ref = quote(frame_id, safe="")
        account_ref = quote(account_id, safe="")
        self._request(
            "PUT",
            f"/frames/{frame_ref}/calendars/{account_ref}",
            {"active_calendars": list(_unique_refs(active_calendar_refs))},
        )

    def _request(
        self, method: str, path: str, body: Mapping[str, Any] | None = None
    ) -> Mapping[str, Any]:
        return self._transport(method, path, body, self.token_provider.get_token())

    def _http_request(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | None,
        token: str,
    ) -> Mapping[str, Any]:
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(
            f"{self.base_url}{path}",
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "skylight-api-version": SKYLIGHT_API_VERSION,
            },
            method=method,
        )
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read()
        except HTTPError as exc:
            raise SkylightApiError(exc.code) from exc
        if not raw:
            return {}
        result = json.loads(raw.decode("utf-8"))
        if not isinstance(result, Mapping):
            raise RuntimeError("Skylight API response was not an object")
        return result


class SkylightVisibilityReconciler:
    """Plan first and apply only an explicitly authorized visibility update."""

    def __init__(self, client: SkylightCalendarClient) -> None:
        self.client = client

    def plan(
        self,
        *,
        frame_id: str,
        account_id: str,
        routes: Sequence[DisplayCalendarRoute],
    ) -> SkylightActivationPlan:
        accounts = self.client.list_calendar_accounts(frame_id)
        account = next(
            (candidate for candidate in accounts if candidate.account_id == account_id),
            None,
        )
        if account is None:
            raise RuntimeError("Configured Skylight calendar account was not found")
        return plan_calendar_activation(account, routes)

    def apply(
        self,
        *,
        frame_id: str,
        account_id: str,
        routes: Sequence[DisplayCalendarRoute],
    ) -> SkylightActivationPlan:
        plan = self.plan(frame_id=frame_id, account_id=account_id, routes=routes)
        if plan.changed:
            self.client.update_active_calendars(
                frame_id=frame_id,
                account_id=account_id,
                active_calendar_refs=plan.desired_active_refs,
            )
        return plan


def _normalize_routes(
    routes: Sequence[DisplayCalendarRoute],
) -> tuple[DisplayCalendarRoute, ...]:
    normalized: list[DisplayCalendarRoute] = []
    visibility_by_ref: dict[str, bool] = {}
    for route in routes:
        ref = str(route.external_calendar_ref).strip()
        if not ref:
            raise ValueError("display calendar route has an empty external reference")
        previous = visibility_by_ref.get(ref)
        if previous is not None and previous != route.visible:
            raise ValueError(f"conflicting visibility policy for calendar reference: {ref}")
        if ref not in visibility_by_ref:
            normalized.append(DisplayCalendarRoute(ref, route.visible))
        visibility_by_ref[ref] = route.visible
    return tuple(normalized)


def _unique_refs(values: Sequence[Any]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        ref = str(value).strip()
        if not ref or ref in seen:
            continue
        seen.add(ref)
        result.append(ref)
    return tuple(result)


def _resources(document: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    data = document.get("data", [])
    values = data if isinstance(data, list) else [data]
    resources: list[Mapping[str, Any]] = []
    for value in values:
        if isinstance(value, Mapping) and value.get("id") not in (None, ""):
            resources.append(value)
    return resources
