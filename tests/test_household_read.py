from __future__ import annotations

import io
import json
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request

from household_os.household_read import (
    DEFAULT_MAX_RESPONSE_BYTES,
    HouseConfig,
    HouseRpcTransport,
    HouseholdReadError,
    _RefusingRedirectHandler,
    fetch_day_brief,
    fetch_day_brief_from_env,
    load_config,
    rpc_function_name,
    validate_boot_response,
    validate_date,
    validate_house_origin,
    validate_timezone,
    validate_viewer,
)
from household_os.read_cli import main


ORIGIN = "https://project-demo.supabase.co"
SERVICE_KEY = "synthetic-service-role-key"
VIEWER = "shared"
DATE = "2030-09-10"
TIMEZONE = "UTC"
NOW = datetime(2030, 9, 10, 12, 0, 0, tzinfo=timezone.utc)


def valid_boot(
    *,
    viewer: str = VIEWER,
    rpcs: list[str] | None = None,
    integrity: str = "match",
    drift: Any = 0,
    booted_at: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "viewer": viewer,
        "capabilities": {
            "rpcs": rpcs
            or ["day_brief(viewer, date, tz)", "session_boot(viewer)"],
        },
        "instruction_integrity": integrity,
        "health": {"capability_manifest_stale": drift},
        "booted_at": booted_at or NOW.isoformat(),
        "topics": ["secret-topic-should-not-appear"],
        "inbox": {"debug": "secret-inbox"},
    }
    if extra:
        payload.update(extra)
    return payload


def valid_brief(
    *,
    viewer: str = VIEWER,
    date: str = DATE,
    events: list[Any] | None = None,
    lunch: Any = None,
    include_nullable_keys: bool = True,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "viewer": viewer,
        "date": date,
        "weekday": "Tuesday",
        "events": events if events is not None else [],
        "channel_open": [],
    }
    if include_nullable_keys:
        payload["school"] = {"name": "synthetic-school"}
        payload["lunch"] = lunch
        payload["menu_coverage"] = {"status": "not_evaluated"}
    return payload


class FakeResponse:
    def __init__(self, body: bytes, url: str) -> None:
        self._body = body
        self._url = url

    def read(self, size: int = -1) -> bytes:
        return self._body[:size] if size >= 0 else self._body

    def geturl(self) -> str:
        return self._url

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


class ScriptedOpener:
    def __init__(self, handlers: list[Any]) -> None:
        self.handlers = list(handlers)
        self.requests: list[Request] = []

    def open(self, request: Request, timeout: float | None = None) -> FakeResponse:
        self.requests.append(request)
        if not self.handlers:
            raise HTTPError(
                request.full_url,
                500,
                "server error",
                hdrs=None,
                fp=io.BytesIO(b'{"message":"SENTINEL-SECRET-VALUE"}'),
            )
        handler = self.handlers.pop(0)
        if isinstance(handler, Exception):
            raise handler
        body = json.dumps(handler).encode("utf-8")
        return FakeResponse(body, request.full_url)


class HouseholdReadValidationTests(unittest.TestCase):
    def test_validate_date_rejects_bad_format(self) -> None:
        with self.assertRaises(HouseholdReadError) as ctx:
            validate_date("09-10-2030")
        self.assertEqual(ctx.exception.code, "invalid_date")

    def test_validate_date_rejects_non_canonical_month_day(self) -> None:
        with self.assertRaises(HouseholdReadError) as ctx:
            validate_date("2030-9-10")
        self.assertEqual(ctx.exception.code, "invalid_date")

    def test_validate_viewer_rejects_empty(self) -> None:
        with self.assertRaises(HouseholdReadError) as ctx:
            validate_viewer("   ")
        self.assertEqual(ctx.exception.code, "invalid_viewer")

    def test_validate_timezone_uses_utc_fixture(self) -> None:
        self.assertEqual(validate_timezone("UTC"), "UTC")

    def test_validate_house_origin_rejects_path(self) -> None:
        with self.assertRaises(HouseholdReadError) as ctx:
            validate_house_origin("https://project-demo.supabase.co/rest/v1")
        self.assertEqual(ctx.exception.code, "config_invalid_url")

    def test_validate_house_origin_rejects_whitespace(self) -> None:
        with self.assertRaises(HouseholdReadError) as ctx:
            validate_house_origin("https://project-demo.supabase.co ")
        self.assertEqual(ctx.exception.code, "config_invalid_url")

    def test_validate_house_origin_rejects_userinfo(self) -> None:
        with self.assertRaises(HouseholdReadError) as ctx:
            validate_house_origin("https://user:pass@project-demo.supabase.co")
        self.assertEqual(ctx.exception.code, "config_invalid_url")

    def test_validate_house_origin_rejects_malformed_port(self) -> None:
        with self.assertRaises(HouseholdReadError) as ctx:
            validate_house_origin("https://project-demo.supabase.co:abc")
        self.assertEqual(ctx.exception.code, "config_invalid_url")

    def test_validate_house_origin_accepts_ipv6(self) -> None:
        origin = validate_house_origin("https://[2001:db8::1]")
        self.assertEqual(origin, "https://[2001:db8::1]")

    def test_house_config_rejects_http_origin(self) -> None:
        with self.assertRaises(HouseholdReadError) as ctx:
            HouseConfig(origin="http://project-demo.supabase.co", service_role_key=SERVICE_KEY)
        self.assertEqual(ctx.exception.code, "config_invalid_url")

    def test_rpc_function_name_is_exact_not_substring(self) -> None:
        self.assertEqual(
            rpc_function_name("day_brief(viewer, date, tz)"), "day_brief"
        )
        self.assertEqual(
            rpc_function_name("not_day_brief(viewer, date, tz)"),
            "not_day_brief",
        )


class HouseholdReadBootTests(unittest.TestCase):
    def test_boot_rejects_wrong_viewer(self) -> None:
        with self.assertRaises(HouseholdReadError) as ctx:
            validate_boot_response(valid_boot(viewer="other"), VIEWER, NOW)
        self.assertEqual(ctx.exception.code, "boot_viewer_mismatch")

    def test_boot_rejects_missing_day_brief_capability(self) -> None:
        with self.assertRaises(HouseholdReadError) as ctx:
            validate_boot_response(
                valid_boot(rpcs=["not_day_brief(viewer, date, tz)"]),
                VIEWER,
                NOW,
            )
        self.assertEqual(ctx.exception.code, "boot_capability_missing")

    def test_boot_rejects_integrity_mismatch(self) -> None:
        with self.assertRaises(HouseholdReadError) as ctx:
            validate_boot_response(
                valid_boot(integrity="drift"), VIEWER, NOW
            )
        self.assertEqual(ctx.exception.code, "boot_integrity_mismatch")

    def test_boot_rejects_bool_drift(self) -> None:
        with self.assertRaises(HouseholdReadError) as ctx:
            validate_boot_response(valid_boot(drift=False), VIEWER, NOW)
        self.assertEqual(ctx.exception.code, "boot_drift_detected")

    def test_boot_rejects_nonzero_drift(self) -> None:
        with self.assertRaises(HouseholdReadError) as ctx:
            validate_boot_response(valid_boot(drift=1), VIEWER, NOW)
        self.assertEqual(ctx.exception.code, "boot_drift_detected")

    def test_boot_rejects_stale_booted_at(self) -> None:
        stale = (NOW - timedelta(minutes=6)).isoformat()
        with self.assertRaises(HouseholdReadError) as ctx:
            validate_boot_response(valid_boot(booted_at=stale), VIEWER, NOW)
        self.assertEqual(ctx.exception.code, "boot_stale")

    def test_boot_rejects_future_booted_at(self) -> None:
        future = (NOW + timedelta(minutes=2)).isoformat()
        with self.assertRaises(HouseholdReadError) as ctx:
            validate_boot_response(valid_boot(booted_at=future), VIEWER, NOW)
        self.assertEqual(ctx.exception.code, "boot_future")

    def test_boot_rejects_naive_booted_at(self) -> None:
        with self.assertRaises(HouseholdReadError) as ctx:
            validate_boot_response(
                valid_boot(booted_at="2030-09-10T12:00:00"), VIEWER, NOW
            )
        self.assertEqual(ctx.exception.code, "boot_malformed")

    def test_boot_rejects_malformed_booted_at_type(self) -> None:
        with self.assertRaises(HouseholdReadError) as ctx:
            validate_boot_response(valid_boot(booted_at=123), VIEWER, NOW)
        self.assertEqual(ctx.exception.code, "boot_malformed")


class HouseholdReadFlowTests(unittest.TestCase):
    def _transport(self, opener: ScriptedOpener) -> HouseRpcTransport:
        config = HouseConfig(origin=ORIGIN, service_role_key=SERVICE_KEY)
        return HouseRpcTransport(config, opener=opener)

    def test_success_returns_scoped_coverage_and_data(self) -> None:
        opener = ScriptedOpener([valid_boot(), valid_brief()])
        transport = self._transport(opener)
        result = fetch_day_brief(
            HouseConfig(origin=ORIGIN, service_role_key=SERVICE_KEY),
            viewer=VIEWER,
            date_str=DATE,
            timezone_str=TIMEZONE,
            transport=transport,
            now=lambda: NOW,
        )
        self.assertEqual(result["coverage"], "queried_house_for_requested_date")
        self.assertEqual(result["data"]["date"], DATE)
        self.assertEqual(result["data"]["events"], [])
        self.assertNotIn("topics", result)
        self.assertNotIn("inbox", result)

    def test_fetch_day_brief_validates_inputs_before_io(self) -> None:
        opener = ScriptedOpener([valid_boot(), valid_brief()])
        transport = self._transport(opener)
        with self.assertRaises(HouseholdReadError) as ctx:
            fetch_day_brief(
                HouseConfig(origin=ORIGIN, service_role_key=SERVICE_KEY),
                viewer="",
                date_str=DATE,
                timezone_str=TIMEZONE,
                transport=transport,
                now=lambda: NOW,
            )
        self.assertEqual(ctx.exception.code, "invalid_viewer")
        self.assertEqual(len(opener.requests), 0)

    def test_fetch_day_brief_rejects_config_transport_mismatch(self) -> None:
        opener = ScriptedOpener([valid_boot(), valid_brief()])
        transport = HouseRpcTransport(
            HouseConfig(origin="https://other.invalid", service_role_key=SERVICE_KEY),
            opener=opener,
        )
        with self.assertRaises(HouseholdReadError) as ctx:
            fetch_day_brief(
                HouseConfig(origin=ORIGIN, service_role_key=SERVICE_KEY),
                viewer=VIEWER,
                date_str=DATE,
                timezone_str=TIMEZONE,
                transport=transport,
                now=lambda: NOW,
            )
        self.assertEqual(ctx.exception.code, "config_transport_mismatch")
        self.assertEqual(len(opener.requests), 0)

    def test_empty_valid_brief_is_scoped_not_absent(self) -> None:
        opener = ScriptedOpener(
            [valid_boot(), valid_brief(events=[], lunch=None)]
        )
        transport = self._transport(opener)
        result = fetch_day_brief(
            HouseConfig(origin=ORIGIN, service_role_key=SERVICE_KEY),
            viewer=VIEWER,
            date_str=DATE,
            timezone_str=TIMEZONE,
            transport=transport,
            now=lambda: NOW,
        )
        self.assertEqual(result["data"]["lunch"], None)
        self.assertEqual(result["data"]["events"], [])
        self.assertNotIn("absent", json.dumps(result))

    def test_call_order_boot_before_brief(self) -> None:
        opener = ScriptedOpener([valid_boot(), valid_brief()])
        transport = self._transport(opener)
        fetch_day_brief(
            HouseConfig(origin=ORIGIN, service_role_key=SERVICE_KEY),
            viewer=VIEWER,
            date_str=DATE,
            timezone_str=TIMEZONE,
            transport=transport,
            now=lambda: NOW,
        )
        self.assertEqual(len(opener.requests), 2)
        self.assertIn("/rpc/session_boot", opener.requests[0].full_url)
        self.assertIn("/rpc/day_brief", opener.requests[1].full_url)

    def test_boot_failure_skips_day_brief(self) -> None:
        opener = ScriptedOpener(
            [valid_boot(viewer="wrong-viewer"), valid_brief()]
        )
        transport = self._transport(opener)
        with self.assertRaises(HouseholdReadError):
            fetch_day_brief(
                HouseConfig(origin=ORIGIN, service_role_key=SERVICE_KEY),
                viewer=VIEWER,
                date_str=DATE,
                timezone_str=TIMEZONE,
                transport=transport,
                now=lambda: NOW,
            )
        self.assertEqual(len(opener.requests), 1)

    def test_wrong_brief_viewer_fails(self) -> None:
        opener = ScriptedOpener(
            [valid_boot(), valid_brief(viewer="other")]
        )
        transport = self._transport(opener)
        with self.assertRaises(HouseholdReadError) as ctx:
            fetch_day_brief(
                HouseConfig(origin=ORIGIN, service_role_key=SERVICE_KEY),
                viewer=VIEWER,
                date_str=DATE,
                timezone_str=TIMEZONE,
                transport=transport,
                now=lambda: NOW,
            )
        self.assertEqual(ctx.exception.code, "brief_viewer_mismatch")

    def test_wrong_brief_date_fails(self) -> None:
        opener = ScriptedOpener(
            [valid_boot(), valid_brief(date="2030-09-11")]
        )
        transport = self._transport(opener)
        with self.assertRaises(HouseholdReadError) as ctx:
            fetch_day_brief(
                HouseConfig(origin=ORIGIN, service_role_key=SERVICE_KEY),
                viewer=VIEWER,
                date_str=DATE,
                timezone_str=TIMEZONE,
                transport=transport,
                now=lambda: NOW,
            )
        self.assertEqual(ctx.exception.code, "brief_date_mismatch")

    def test_missing_required_nullable_brief_keys_fails(self) -> None:
        opener = ScriptedOpener(
            [valid_boot(), valid_brief(include_nullable_keys=False)]
        )
        transport = self._transport(opener)
        with self.assertRaises(HouseholdReadError) as ctx:
            fetch_day_brief(
                HouseConfig(origin=ORIGIN, service_role_key=SERVICE_KEY),
                viewer=VIEWER,
                date_str=DATE,
                timezone_str=TIMEZONE,
                transport=transport,
                now=lambda: NOW,
            )
        self.assertEqual(ctx.exception.code, "brief_malformed")
        self.assertEqual(len(opener.requests), 2)

    def test_malformed_event_element_fails_without_extra_rpc(self) -> None:
        opener = ScriptedOpener(
            [valid_boot(), valid_brief(events=["not-a-dict"])]
        )
        transport = self._transport(opener)
        with self.assertRaises(HouseholdReadError) as ctx:
            fetch_day_brief(
                HouseConfig(origin=ORIGIN, service_role_key=SERVICE_KEY),
                viewer=VIEWER,
                date_str=DATE,
                timezone_str=TIMEZONE,
                transport=transport,
                now=lambda: NOW,
            )
        self.assertEqual(ctx.exception.code, "brief_malformed")
        self.assertEqual(len(opener.requests), 2)

    def test_malformed_channel_element_fails(self) -> None:
        brief = valid_brief()
        brief["channel_open"] = ["bad"]
        opener = ScriptedOpener([valid_boot(), brief])
        transport = self._transport(opener)
        with self.assertRaises(HouseholdReadError) as ctx:
            fetch_day_brief(
                HouseConfig(origin=ORIGIN, service_role_key=SERVICE_KEY),
                viewer=VIEWER,
                date_str=DATE,
                timezone_str=TIMEZONE,
                transport=transport,
                now=lambda: NOW,
            )
        self.assertEqual(ctx.exception.code, "brief_malformed")

    def test_inaccessible_store_maps_to_transport_error(self) -> None:
        broken = ScriptedOpener(
            [
                HTTPError(
                    ORIGIN + "/rest/v1/rpc/session_boot",
                    500,
                    "err",
                    hdrs=None,
                    fp=io.BytesIO(
                        b'{"message":"SENTINEL-SECRET-VALUE"}'
                    ),
                )
            ]
        )
        transport = self._transport(broken)
        with self.assertRaises(HouseholdReadError) as ctx:
            fetch_day_brief(
                HouseConfig(origin=ORIGIN, service_role_key=SERVICE_KEY),
                viewer=VIEWER,
                date_str=DATE,
                timezone_str=TIMEZONE,
                transport=transport,
                now=lambda: NOW,
            )
        self.assertEqual(ctx.exception.code, "transport_error")

    def test_malformed_brief_payload(self) -> None:
        opener = ScriptedOpener([valid_boot(), {"viewer": VIEWER, "date": DATE}])
        transport = self._transport(opener)
        with self.assertRaises(HouseholdReadError) as ctx:
            fetch_day_brief(
                HouseConfig(origin=ORIGIN, service_role_key=SERVICE_KEY),
                viewer=VIEWER,
                date_str=DATE,
                timezone_str=TIMEZONE,
                transport=transport,
                now=lambda: NOW,
            )
        self.assertEqual(ctx.exception.code, "brief_malformed")

    def test_transport_error_hides_secret_sentinel(self) -> None:
        opener = ScriptedOpener([])
        transport = self._transport(opener)
        with self.assertRaises(HouseholdReadError) as ctx:
            fetch_day_brief(
                HouseConfig(origin=ORIGIN, service_role_key=SERVICE_KEY),
                viewer=VIEWER,
                date_str=DATE,
                timezone_str=TIMEZONE,
                transport=transport,
                now=lambda: NOW,
            )
        self.assertEqual(ctx.exception.code, "transport_error")
        self.assertNotIn("SENTINEL", ctx.exception.code)

    def test_disallowed_rpc_rejected(self) -> None:
        transport = self._transport(ScriptedOpener([]))
        with self.assertRaises(HouseholdReadError) as ctx:
            transport.call_rpc("other_rpc", {})
        self.assertEqual(ctx.exception.code, "rpc_not_allowed")

    def test_response_too_large_rejected(self) -> None:
        huge = b"x" * (DEFAULT_MAX_RESPONSE_BYTES + 1)
        opener = ScriptedOpener([])

        def _open(request: Request, timeout: float | None = None) -> FakeResponse:
            opener.requests.append(request)
            return FakeResponse(huge, request.full_url)

        opener.open = _open  # type: ignore[method-assign]
        transport = self._transport(opener)
        with self.assertRaises(HouseholdReadError) as ctx:
            transport.call_rpc("session_boot", {"p_viewer": VIEWER})
        self.assertEqual(ctx.exception.code, "response_too_large")

    def test_transport_rejects_invalid_timeout(self) -> None:
        config = HouseConfig(origin=ORIGIN, service_role_key=SERVICE_KEY)
        with self.assertRaises(HouseholdReadError) as ctx:
            HouseRpcTransport(config, timeout_seconds=0)
        self.assertEqual(ctx.exception.code, "config_invalid_transport")

    def test_transport_rejects_bool_max_response_bytes(self) -> None:
        config = HouseConfig(origin=ORIGIN, service_role_key=SERVICE_KEY)
        with self.assertRaises(HouseholdReadError) as ctx:
            HouseRpcTransport(config, max_response_bytes=True)  # type: ignore[arg-type]
        self.assertEqual(ctx.exception.code, "config_invalid_transport")

    def test_redirect_handler_refuses_same_origin_before_forwarding(self) -> None:
        handler = _RefusingRedirectHandler()
        request = Request(
            f"{ORIGIN}/rest/v1/rpc/session_boot",
            method="POST",
        )
        forwarded: list[Request] = []
        handler.parent = type(
            "Parent",
            (),
            {"open": lambda self, req, timeout=None: forwarded.append(req)},
        )()
        with self.assertRaises(HouseholdReadError) as ctx:
            handler.redirect_request(
                request,
                None,
                302,
                "",
                {},
                f"{ORIGIN}/rest/v1/rpc/session_boot",
            )
        self.assertEqual(ctx.exception.code, "redirect_refused")
        self.assertEqual(forwarded, [])

    def test_redirect_handler_refuses_cross_origin_before_forwarding(self) -> None:
        handler = _RefusingRedirectHandler()
        request = Request(
            f"{ORIGIN}/rest/v1/rpc/session_boot",
            method="POST",
        )
        forwarded: list[Request] = []
        handler.parent = type(
            "Parent",
            (),
            {"open": lambda self, req, timeout=None: forwarded.append(req)},
        )()
        with self.assertRaises(HouseholdReadError) as ctx:
            handler.redirect_request(
                request,
                None,
                302,
                "",
                {},
                "https://evil.invalid/rest/v1/rpc/session_boot",
            )
        self.assertEqual(ctx.exception.code, "redirect_refused")
        self.assertEqual(forwarded, [])

    def test_redirect_final_url_mismatch_refused(self) -> None:
        class RedirectFinalUrlOpener:
            def __init__(self) -> None:
                self.requests: list[Request] = []

            def open(
                self, request: Request, timeout: float | None = None
            ) -> FakeResponse:
                self.requests.append(request)
                body = json.dumps(valid_boot()).encode("utf-8")
                return FakeResponse(
                    body,
                    f"{ORIGIN}/rest/v1/rpc/session_boot?redirected=1",
                )

        opener = RedirectFinalUrlOpener()
        transport = self._transport(opener)  # type: ignore[arg-type]
        with self.assertRaises(HouseholdReadError) as ctx:
            transport.call_rpc("session_boot", {"p_viewer": VIEWER})
        self.assertEqual(ctx.exception.code, "redirect_refused")
        self.assertEqual(len(opener.requests), 1)
        auth = opener.requests[0].headers.get("Authorization", "")
        self.assertTrue(auth.startswith("Bearer "))
        self.assertNotIn("redirected=1", auth)


class HouseholdReadConfigTests(unittest.TestCase):
    def test_invalid_config_missing_url_no_transport(self) -> None:
        with unittest.mock.patch(
            "household_os.household_read.build_opener"
        ) as mock_build:
            with self.assertRaises(HouseholdReadError) as ctx:
                load_config({"HOUSE_SUPABASE_SERVICE_ROLE_KEY": SERVICE_KEY})
            self.assertEqual(ctx.exception.code, "config_missing_url")
            mock_build.assert_not_called()

    def test_invalid_config_missing_key_no_transport(self) -> None:
        with unittest.mock.patch(
            "household_os.household_read.build_opener"
        ) as mock_build:
            with self.assertRaises(HouseholdReadError) as ctx:
                load_config({"HOUSE_SUPABASE_URL": ORIGIN})
            self.assertEqual(ctx.exception.code, "config_missing_key")
            mock_build.assert_not_called()

    def test_invalid_config_url_no_fetch_io(self) -> None:
        with unittest.mock.patch(
            "household_os.household_read.build_opener"
        ) as mock_build:
            with self.assertRaises(HouseholdReadError) as ctx:
                fetch_day_brief_from_env(
                    viewer=VIEWER,
                    date_str=DATE,
                    timezone_str=TIMEZONE,
                    env={"HOUSE_SUPABASE_URL": "http://insecure.invalid", "HOUSE_SUPABASE_SERVICE_ROLE_KEY": SERVICE_KEY},
                )
            self.assertEqual(ctx.exception.code, "config_invalid_url")
            mock_build.assert_not_called()


class HouseholdReadCliTests(unittest.TestCase):
    def test_missing_live_read_performs_no_io(self) -> None:
        stderr = io.StringIO()
        with unittest.mock.patch("sys.stderr", stderr), unittest.mock.patch(
            "household_os.household_read.load_config"
        ) as mock_load, unittest.mock.patch(
            "household_os.read_cli.fetch_day_brief_from_env"
        ) as mock_fetch, unittest.mock.patch(
            "household_os.read_cli.os.environ",
            {"HOUSE_SUPABASE_URL": ORIGIN, "HOUSE_SUPABASE_SERVICE_ROLE_KEY": SERVICE_KEY},
        ):
            code = main(["--date", DATE, "--timezone", "UTC"])
        self.assertEqual(code, 1)
        self.assertEqual(stderr.getvalue().strip(), "live_read_required")
        mock_load.assert_not_called()
        mock_fetch.assert_not_called()

    def test_invalid_date_before_config_access(self) -> None:
        stderr = io.StringIO()
        with unittest.mock.patch("sys.stderr", stderr), unittest.mock.patch(
            "household_os.household_read.load_config"
        ) as mock_load:
            code = main(
                ["--date", "bad-date", "--timezone", "UTC", "--live-read"]
            )
        self.assertEqual(code, 1)
        self.assertEqual(stderr.getvalue().strip(), "invalid_date")
        mock_load.assert_not_called()

    def test_invalid_timezone_before_config_access(self) -> None:
        stderr = io.StringIO()
        with unittest.mock.patch("sys.stderr", stderr), unittest.mock.patch(
            "household_os.household_read.load_config"
        ) as mock_load:
            code = main(
                ["--date", DATE, "--timezone", "Not/A/Timezone", "--live-read"]
            )
        self.assertEqual(code, 1)
        self.assertIn(
            stderr.getvalue().strip(),
            ("invalid_timezone", "timezone_unavailable"),
        )
        mock_load.assert_not_called()

    def test_unexpected_failure_is_stable_and_hides_sentinel(self) -> None:
        stderr = io.StringIO()
        stdout = io.StringIO()
        with unittest.mock.patch("sys.stderr", stderr), unittest.mock.patch(
            "sys.stdout", stdout
        ), unittest.mock.patch(
            "household_os.read_cli.fetch_day_brief_from_env",
            side_effect=RuntimeError("SENTINEL-SECRET-VALUE"),
        ):
            code = main(
                ["--date", DATE, "--timezone", "UTC", "--live-read"]
            )
        self.assertEqual(code, 1)
        self.assertEqual(stderr.getvalue().strip(), "command_failed")
        self.assertEqual(stdout.getvalue().strip(), '{"coverage":"unavailable"}')
        self.assertNotIn("SENTINEL", stderr.getvalue())
        self.assertNotIn("SENTINEL", stdout.getvalue())

    def test_success_via_injected_rpc_without_sockets(self) -> None:
        opener = ScriptedOpener([valid_boot(), valid_brief()])
        config = HouseConfig(origin=ORIGIN, service_role_key=SERVICE_KEY)
        transport = HouseRpcTransport(config, opener=opener)

        def _fetch(**kwargs: object) -> dict[str, object]:
            return fetch_day_brief(
                config,
                viewer=str(kwargs["viewer"]),
                date_str=str(kwargs["date_str"]),
                timezone_str=str(kwargs["timezone_str"]),
                transport=transport,
                now=lambda: NOW,
            )

        with unittest.mock.patch(
            "household_os.read_cli.fetch_day_brief_from_env",
            side_effect=_fetch,
        ):
            stdout = io.StringIO()
            with unittest.mock.patch("sys.stdout", stdout):
                code = main(
                    [
                        "--date",
                        DATE,
                        "--timezone",
                        "UTC",
                        "--live-read",
                    ]
                )
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(
            payload["coverage"], "queried_house_for_requested_date"
        )
        self.assertEqual(len(opener.requests), 2)


if __name__ == "__main__":
    unittest.main()
