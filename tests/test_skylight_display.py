from __future__ import annotations

import unittest
from typing import Any, Mapping

from household_os.skylight_display import (
    DisplayCalendarRoute,
    SkylightAccessTokenProvider,
    SkylightCalendarAccount,
    SkylightCalendarClient,
    SkylightVisibilityReconciler,
    plan_calendar_activation,
)


class StaticToken:
    def get_token(self) -> str:
        return "synthetic-token"


class ActivationPlanningTests(unittest.TestCase):
    def test_preserves_unmanaged_adds_visible_and_removes_hidden(self) -> None:
        account = SkylightCalendarAccount(
            account_id="account-demo",
            active_calendar_refs=("family-demo", "house-lunch", "work-demo"),
        )
        plan = plan_calendar_activation(
            account,
            (
                DisplayCalendarRoute("house-no-school", True),
                DisplayCalendarRoute("house-lunch", False),
                DisplayCalendarRoute("house-conferences", True),
            ),
        )

        self.assertEqual(
            plan.desired_active_refs,
            (
                "family-demo",
                "work-demo",
                "house-no-school",
                "house-conferences",
            ),
        )
        self.assertEqual(
            plan.added_refs, ("house-no-school", "house-conferences")
        )
        self.assertEqual(plan.removed_refs, ("house-lunch",))

    def test_same_policy_is_noop(self) -> None:
        account = SkylightCalendarAccount(
            account_id="account-demo",
            active_calendar_refs=("house-no-school", "family-demo"),
        )
        plan = plan_calendar_activation(
            account,
            (
                DisplayCalendarRoute("house-no-school", True),
                DisplayCalendarRoute("house-lunch", False),
            ),
        )
        self.assertFalse(plan.changed)
        self.assertEqual(
            plan.desired_active_refs, ("house-no-school", "family-demo")
        )
        self.assertEqual(plan.added_refs, ())
        self.assertEqual(plan.removed_refs, ())

    def test_conflicting_duplicate_route_is_rejected(self) -> None:
        account = SkylightCalendarAccount("account-demo", ())
        with self.assertRaisesRegex(ValueError, "conflicting visibility"):
            plan_calendar_activation(
                account,
                (
                    DisplayCalendarRoute("house-demo", True),
                    DisplayCalendarRoute("house-demo", False),
                ),
            )


class ClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[tuple[str, str, Mapping[str, Any] | None, str]] = []

        def transport(
            method: str, path: str, body: Mapping[str, Any] | None, token: str
        ) -> Mapping[str, Any]:
            self.calls.append((method, path, body, token))
            if path == "/frames":
                return {"data": [{"id": "frame-demo", "attributes": {}}]}
            if method == "GET":
                return {
                    "data": [
                        {
                            "id": "account-demo",
                            "type": "calendar",
                            "attributes": {
                                "active_calendars": ["family-demo", "house-lunch"]
                            },
                        }
                    ]
                }
            return {"data": {"id": "account-demo", "attributes": {}}}

        self.client = SkylightCalendarClient(StaticToken(), transport=transport)

    def test_resolves_single_frame_and_lists_calendar_accounts(self) -> None:
        self.assertEqual(self.client.resolve_frame_id(), "frame-demo")
        accounts = self.client.list_calendar_accounts("frame-demo")
        self.assertEqual(
            accounts,
            (
                SkylightCalendarAccount(
                    "account-demo", ("family-demo", "house-lunch")
                ),
            ),
        )
        self.assertEqual(self.calls[0][1], "/frames")
        self.assertEqual(self.calls[1][1], "/frames/frame-demo/calendars")

    def test_reconciler_plan_does_not_write(self) -> None:
        reconciler = SkylightVisibilityReconciler(self.client)
        plan = reconciler.plan(
            frame_id="frame-demo",
            account_id="account-demo",
            routes=(DisplayCalendarRoute("house-lunch", False),),
        )
        self.assertTrue(plan.changed)
        self.assertEqual([call[0] for call in self.calls], ["GET"])

    def test_reconciler_apply_writes_only_desired_active_refs(self) -> None:
        reconciler = SkylightVisibilityReconciler(self.client)
        plan = reconciler.apply(
            frame_id="frame-demo",
            account_id="account-demo",
            routes=(
                DisplayCalendarRoute("house-no-school", True),
                DisplayCalendarRoute("house-lunch", False),
            ),
        )
        self.assertEqual(
            plan.desired_active_refs, ("family-demo", "house-no-school")
        )
        self.assertEqual(self.calls[-1][0], "PUT")
        self.assertEqual(
            self.calls[-1][1], "/frames/frame-demo/calendars/account-demo"
        )
        self.assertEqual(
            self.calls[-1][2],
            {"active_calendars": ["family-demo", "house-no-school"]},
        )

    def test_missing_account_is_bounded(self) -> None:
        reconciler = SkylightVisibilityReconciler(self.client)
        with self.assertRaisesRegex(RuntimeError, "was not found"):
            reconciler.plan(
                frame_id="frame-demo",
                account_id="missing-demo",
                routes=(),
            )


class TokenTests(unittest.TestCase):
    def test_household_password_is_not_an_auth_fallback(self) -> None:
        provider = SkylightAccessTokenProvider(
            {"HOUSE_SKYLIGHT_PASSWORD": "must-not-be-used"}
        )
        with self.assertRaisesRegex(RuntimeError, "access is unavailable"):
            provider.get_token()


if __name__ == "__main__":
    unittest.main()
