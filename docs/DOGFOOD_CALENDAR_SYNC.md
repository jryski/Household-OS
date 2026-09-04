# Calendar delivery dogfood runbook

> **Status:** first executable slice
> **Data rule:** credentials, provider IDs, event content, and dogfood output stay outside Git

## Outcome

The worker reconciles canonical HOUSE events from the service-only `calendar_delivery_outbox` to Google Calendar and records the external event identity back in `calendar_event_links`.

The first dogfood route is `school.lunch`:

```text
canonical HOUSE lunch event
        ↓
gcal-school-lunch delivery rule
        ↓
native Google secondary calendar
        ├── queryable by an authorized Gemini / Google Home account
        └── hidden by default on the household display
```

Google is a delivery copy. HOUSE remains canonical for meal content, source evidence, conflicts, and lifecycle.

## Implemented behavior

- Dry-run planning is the default safe operation.
- Live sync requires an explicit `sync --live` command.
- Provider event IDs are deterministic, so a process crash between Google creation and HOUSE receipt persistence does not create a duplicate on retry.
- Existing links are updated in place when the canonical hash changes.
- Success and bounded failure receipts are written through service-role-only database functions.
- Google events are private, transparent/non-blocking, and have reminders disabled.
- Direct Google API delivery uses true all-day events.
- Connectors without true all-day creation use the explicit `12:00 AM`–`11:59 PM` local-time fallback.
- Output reports counts only; it does not print event titles, provider IDs, or household content.
- A service-role-only `get_household_lunch(date, timezone)` function gives authorized agents a canonical HOUSE query path.

## Prerequisites

The deployment must already contain the canonical event and delivery tables documented in [`IMAGE_CALENDAR_INTAKE.md`](IMAGE_CALENDAR_INTAKE.md). Apply the migration in `supabase/migrations` to add the worker receipts and lunch query contract.

Copy `.env.example` to an ignored local environment file and supply:

- the Supabase project URL and a server-side service-role secret;
- either a short-lived Google access token or server-side OAuth refresh credentials;
- Google Calendar API consent for event read/write access.

Never put a service-role key, refresh token, calendar ID, or real event payload in this repository. The worker is server-side software; do not bundle it into a browser or mobile client.

## Plan and synchronize

From an activated environment with the package installed:

```text
household-calendar-sync plan \
  --target gcal-school-lunch \
  --category school.lunch
```

The command returns only the number of pending deliveries. Review that scope before the live run.

```text
household-calendar-sync sync \
  --target gcal-school-lunch \
  --category school.lunch \
  --live
```

Use `--limit` for a bounded canary. Use `--force-same-day-2359` only when the active connector cannot create a true all-day provider event.

## Google Home and display setup

After the native secondary calendar is populated:

1. Keep the lunch route enabled in HOUSE.
2. Keep the lunch calendar hidden by default in Skylight or the selected display.
3. In Google Home settings, select the additional lunch calendar for each authorized Voice Match account that should answer lunch questions.
4. Ask a date-specific question and compare the response with the canonical HOUSE query.

Google Home does not treat an imported URL/iCalendar feed as an equivalent assistant-readable calendar. This route therefore requires a native created or shared Google calendar.

## Dogfood acceptance checks

1. `plan` reports the expected bounded scope without provider writes.
2. A one-item canary creates one private, transparent event on the lunch calendar.
3. The provider event ends on the intended date and does not appear on the following day.
4. The corresponding `calendar_event_links` row becomes `synced` with an external ID, canonical hash, provider version when available, and rendering mode.
5. Re-running the same scope creates no duplicate event.
6. Changing one canonical meal causes an update to the linked provider event.
7. Disabling display visibility leaves provider delivery and canonical HOUSE queryability intact.
8. An authorized agent can answer the lunch query from HOUSE; an authorized Gemini or Google Home account can answer from the provider copy.
9. A forced provider failure records an error and leaves the item eligible for retry.
10. Logs, command output, fixtures, and Git history contain no credentials, production IDs, or real household content.
