# Skylight display visibility bridge

> **Status:** experimental calendar-only adapter
> **Data rule:** credentials, frame IDs, account IDs, provider calendar IDs, and live responses stay outside Git

## Outcome

HOUSE should be able to make a connected set of provider calendars visible on Skylight with one setup choice, while keeping low-display-value calendars such as school lunch hidden and preserving every unrelated calendar the household already uses.

The display flow is:

```text
canonical HOUSE event
        ↓
HOUSE category delivery rule
        ↓
native Google secondary calendar
        ↓ official one-way account connection
Skylight active sub-calendar selection
```

HOUSE remains canonical. Google carries the provider copy. Skylight controls display visibility only.

## Why the integration is narrow

The `skylight-mcp` project demonstrates an undocumented Skylight API surface for listing frames, listing calendar accounts, and replacing a calendar account's `active_calendars` list. The project is MIT-licensed, so Household OS may study and reuse that interface with attribution.

Household OS does **not** embed the MCP server or expose its broad tool set. The experimental adapter uses only:

```text
GET /frames
GET /frames/{frame}/calendars
PUT /frames/{frame}/calendars/{calendar-account}
    body: { active_calendars: [...] }
```

No Skylight event, chore, reward, list, photo, meal, family-member, or device endpoint is in scope.

## Safety boundary

The observed Skylight OAuth client issues an `everything` scope rather than a calendar-only scope. That makes the credential more powerful than the operation HOUSE needs.

Until Skylight offers a sanctioned least-privilege integration:

- the default mode is `official_handoff`;
- `experimental_api` is separately opt-in and server-side only;
- HOUSE accepts a short-lived, revocable bearer token and never a Skylight password;
- logs, plans, exceptions, and receipts omit tokens and live provider identifiers;
- a future unattended deployment must persist rotated refresh tokens atomically in an encrypted secret store before it can be called seamless or production-ready;
- authentication or API-shape failure falls back to an exact official one-way connection instruction without interrupting Google delivery.

The adapter's API is intentionally smaller than the credential's authority. That limits what HOUSE code can request, though it cannot make an upstream broad token truly least-privileged.

## Setup flow

1. The household enables calendar delivery and the Skylight display target.
2. HOUSE creates or binds the enabled Google category calendars and records their provider references privately.
3. Skylight's official flow connects the Google account using one-way sync. HOUSE does not accept writes back from Skylight.
4. Setup chooses `official_handoff` or explicitly opts into `experimental_api`.
5. HOUSE resolves one frame and one connected Google calendar account. Multiple matches require a user choice; setup never guesses.
6. HOUSE builds a redacted activation plan from managed category routes:
   - retain every currently active reference not managed by HOUSE;
   - add each HOUSE reference whose display visibility is `true`;
   - remove each HOUSE reference whose display visibility is `false`;
   - deduplicate references while preserving stable order.
7. `plan_only` reports counts. `apply_with_receipt` submits the full desired active list after explicit setup authorization.
8. Setup verifies the resulting visible categories through the display or a follow-up account read and stores a capability/status receipt.

The default school profile keeps closures, schedule changes, conferences, and selected events visible. `school.lunch` remains delivered to Google and queryable by an authorized assistant but hidden on Skylight.

## Implemented code contract

`household_os.skylight_display` contains:

- `plan_calendar_activation`, a pure planner that cannot write externally;
- `SkylightCalendarClient`, a calendar-account-only HTTP adapter;
- `SkylightVisibilityReconciler.plan`, which reads current state and returns a reversible plan;
- `SkylightVisibilityReconciler.apply`, which writes only when the desired active list differs;
- `SkylightAccessTokenProvider`, which accepts only `HOUSE_SKYLIGHT_ACCESS_TOKEN` and deliberately ignores password-like configuration.

The public repository includes only synthetic tests. No live frame, account, calendar, or household identifier belongs in a fixture.

## Failure and drift handling

| Condition | HOUSE behavior |
|---|---|
| No connected Google account | Offer official one-way connection handoff; keep canonical and Google delivery running. |
| Multiple frames or accounts | Require an explicit setup selection and persist only the chosen private reference. |
| Token expired or revoked | Mark display binding degraded; do not alter Google delivery or canonical events. |
| Skylight endpoint or response changed | Stop before write, retain the last known plan, and fall back to official setup. |
| User changes non-HOUSE calendars | Preserve them on the next reconciliation. |
| User changes a HOUSE category directly | Reconcile according to the configured HOUSE visibility policy or surface drift when automatic apply is disabled. |
| Lunch is accidentally active | The next authorized apply removes only the managed lunch reference from Skylight; the Google copy remains. |

## Acceptance criteria

1. Planning performs no external write.
2. Applying a plan preserves every active non-HOUSE calendar.
3. A visible HOUSE route is added once and retries are idempotent.
4. A hidden HOUSE route is removed from Skylight without deleting its provider calendar or canonical events.
5. Conflicting visibility rules for one provider reference fail before any write.
6. Missing or ambiguous frame/account selection fails closed.
7. The adapter exposes no event-writing or destructive display operation.
8. A password cannot be used as an authentication fallback.
9. Errors and command output contain no credential or live household content.
10. API failure leaves the official one-way setup path available.

## Upstream provenance

The endpoint contract, API base/header observations, and risk analysis were informed by `chrischall/skylight-mcp` at the pinned revision recorded in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). Household OS should periodically re-run synthetic conformance tests against a disposable test account before updating that pin. An upstream change is evidence to review, not an instruction to widen HOUSE's adapter.
