# Travel assistance reference implementation

Implements the executable reference slice of [#43](https://github.com/jryski/Household-OS/issues/43): validated booking observations, calendar attachment intake, canonical HOUSE publication, calendar delivery/cancellation, backward departure planning, durable checks/notification retries, and source-labeled transport comparisons.

This is code with synthetic qualification, not a production activation receipt. It does not establish continuous monitoring merely by installing the package or opening the pull request.

## Data path and authority

1. A configured read-only Gmail query supplies calendar attachments, or an operator supplies `.ics` / normalized JSON. Unstructured HTML, PDF and image extraction is a separate existing intake boundary. Those messages are marked for review, never silently treated as parsed bookings.
2. `travel_intake.py` accepts explicit flight/train/hotel events. Repeated UID/revision observations deduplicate. Equal-revision conflicts, unknown event types, recurrence, floating times, unknown zones and DST ambiguity require review. It ignores alarms and does not follow instructions from descriptions.
3. The service stages observations and operational receipts privately. `HouseTravelPublisher` writes the existing `household_events` model, then reads it back. No new HOUSE schema, category, owner, calendar binding, or permission is created. It rejects stale observations, unexpected writers, manual canonical edits and concurrent update conflicts.
4. A live worker requires the canonical HOUSE publisher before calendar writes or notifications. A canonical conflict stops those actions. UTC canonical projection avoids ambiguous time-without-timezone fields while retaining the original zones and evidence reference in metadata. Hotel stays remain date-based, with checkout exclusive at the provider.
5. The worker reuses `DeliveryItem`, `GoogleTokenProvider` and the existing Google renderer/writer. Calendar IDs remain deterministic from canonical event ID and target. Cancellation deletes that managed event idempotently. The reference runner keeps operational delivery receipts in its private state.
6. A known origin, transport mode and configured arrival deadline or predeparture buffer produce a transfer plan. Separate transfer overrides preserve human choices across booking-source revisions. A hotel-to-hub return leg is configured independently from a home-to-hub outbound leg.
7. A supervised bounded tick refreshes forecasts and notifies enrolled recipient keys. The receiver maps keys to real channels and acknowledges a receipt. No email is sent or modified by the intake adapter.

SQLite is **operational staging and the single-host reference runner**, not a replacement HOUSE calendar/work store. Live calendar actions first publish and verify HOUSE. Before a multi-host rollout, replace the local serialization/operational repository with a principal-bound HOUSE worker repository and fenced leases; do not share this SQLite file across hosts. Do not run a second independent calendar writer for the same travel target. The existing reconciler and this reference runner must be assigned disjoint category/target scopes until shared delivery receipts/cancellation reconciliation are unified.

## Departure calculation

`leave_by = required arrival - forecast travel - pickup - parking/shuttle - walking - contingency`

The required arrival deadline is an explicit `arrive_by`, or the scheduled service departure minus a configured `arrival_buffer_minutes`. An earlier sourced cutoff wins. The code does not relax the deadline when an operational delay appears. Airline/rail status and cutoff feeds must supply evidence; the worker does not invent them.

The Google Routes adapter queries predicted traffic at the proposed ground departure, with at most three refinement requests. It retains the longest refinement sample. Samples older than fifteen minutes, future-dated samples, unsupported modes, transport failures and route mismatches fall back to the more conservative configured/last-known duration and label the plan as an estimate. These are forecasts, not guarantees.

The first tick sends only the most relevant stage: briefing within 24 hours of leaving, preparation within one hour, or leave-now once due. A cumulative advance of at least ten minutes generates a changed-plan alert. Old booking revisions, cancelled bookings, obsolete queued advice and elapsed arrival deadlines cannot send pending departure alerts. A worker restart preserves pending deliveries and bounded retry backoff.

Manual origin/mode/buffer configuration is required. Neither a city-level attachment location nor a missing home/hotel address is silently promoted into a navigable terminal destination. The origin timezone may be set independently for correct local notification text.

## Run synthetic examples

From a checkout:

```bash
export PYTHONPATH=src
export HOUSE_TRAVEL_RECIPIENTS=person-1
python -m household_os.travel_cli ingest --db /tmp/travel-demo.sqlite --input examples/travel/booking.json
python -m household_os.travel_cli tick --db /tmp/travel-demo.sqlite
python -m household_os.travel_cli status --db /tmp/travel-demo.sqlite
python -m household_os.travel_cli compare --input examples/travel/options.json
```

The example timestamps are fabricated. Quotes outside their freshness window are deliberately marked stale, not represented as current prices. `tick` without `--live` uses a disposable copy and does not advance persistent check or notification state. No network adapter runs in this mode.

Import a calendar attachment:

```bash
python -m household_os.travel_cli ingest --db /tmp/travel-demo.sqlite \
  --input examples/travel/trip.ics --trip trip-demo --evidence fixture:calendar-demo
```

Use `--kind` only when the source type is otherwise known; it is not inferred from arbitrary event prose. Date-only hotel imports require `--timezone`. Cancellation-only messages without sufficient source identity/times require review. A UID or grouping identity changed by a provider requires reconciliation; do not manufacture an identity match.

An imported attachment does not invent ground transportation. An operator may configure a validated transfer JSON independently:

```bash
python -m household_os.travel_cli configure-transfer --db /path/to/private-state.sqlite \
  --booking-id OPAQUE_BOOKING_KEY --input /path/to/private-transfer.json
```

The opaque key is `digest([trip_id, booking_id])`. Operational status logs intentionally omit traveler identities, itinerary contents and source locators. Access to the private repository for configuring a booking belongs to the deployment operator.

## Service configuration

Only `tick --live` enables configured external actions. It requires explicit canonical HOUSE settings:

| Variable | Purpose |
| --- | --- |
| `HOUSE_SUPABASE_URL` | Existing HOUSE Data API HTTPS origin |
| `HOUSE_SUPABASE_SERVICE_ROLE_KEY` | Existing server-only administrative credential; never client-side |
| `HOUSE_TRAVEL_OWNER` | Existing deployment owner accepted by HOUSE constraints |
| `HOUSE_TRAVEL_VISIBILITY` | Explicit `private` or `shared`, subject to HOUSE owner constraints |
| `HOUSE_TRAVEL_CATEGORY` | Existing category already configured for this travel scope |
| `HOUSE_TRAVEL_SOURCE_AGENT` | Fixed deployment-scoped source identity |
| `HOUSE_TRAVEL_TARGET`, `HOUSE_TRAVEL_CALENDAR_REF` | Explicit managed calendar target and provider calendar |
| Existing `HOUSE_GOOGLE_*` variables | Calendar OAuth access or refresh credentials |
| `HOUSE_ROUTES_API_KEY` | Optional enabled Google Routes API key; absent means labeled fallback |
| `HOUSE_TRAVEL_RECIPIENTS` | Comma-separated enrolled recipient keys |
| `HOUSE_TRAVEL_NOTIFY_URL`, `HOUSE_TRAVEL_NOTIFY_TOKEN` | Configured HTTPS receiver and server-only credential |

The service identity is a trusted server operator, not a model-supplied authorization claim. The broad service key does not provide per-agent authorization. Keep this code server-side and use the program's principal-bound broker before exposing it to agents or multiple users. No new public grants, RLS policies, SECURITY DEFINER functions, stored credentials or live schema changes are introduced.

For unattended Gmail intake, provision a **separate read-only Gmail OAuth grant**, not the Calendar grant:

- `HOUSE_TRAVEL_GMAIL_ACCESS_TOKEN`, or `HOUSE_TRAVEL_GMAIL_CLIENT_ID`, `HOUSE_TRAVEL_GMAIL_CLIENT_SECRET`, `HOUSE_TRAVEL_GMAIL_REFRESH_TOKEN`.
- `HOUSE_TRAVEL_GMAIL_QUERY`: explicitly configured intake scope such as an operator-managed travel label.
- `HOUSE_TRAVEL_DATE_TIMEZONE`: optional IANA zone for date-only hotel attachments.

`poll-inbox --live` reads a bounded page and stores a query-specific pagination cursor. `X-WR-RELCALID` is required for automatic attachment grouping; missing grouping data and unsupported message formats enter review. It does not move, mark read, reply to, or forward messages. The private `travel_mail_seen` table retains hashed message keys and `accepted`/`review` state. Transport failures remain retryable. Private evidence references on staged observations identify the source for review. There is no unattended HTML/PDF/OCR extractor in this slice.

A host supervisor should invoke read-only `poll-inbox --live` and then `tick --live` every minute. Checks are persisted with a five-minute interval. Run one host, a bounded batch, a service credential file readable only by its account, and monitored exit/status output. These commands are not scheduled by package installation. A missing calendar, traffic or notification adapter is listed in tick output; notification failures remain pending with backoff. Wiring a channel without checking its receipt behavior does not complete activation.

### Notification receiver contract

POST JSON body: `{recipient_key, kind, plan}`. `plan` includes local human-readable `message`, origin/destination, booking title, UTC leave-by/arrival instants, duration components, source/quality/age, warnings and any supplied transport comparisons. Types are `brief`, `prepare`, `leave_now`, `changed`.

Headers include `Authorization: Bearer ...` and a stable `Idempotency-Key`. The receiver must persist that key, map only enrolled keys to channels, and return `{ "receipt_id": "..." }` after acceptance. Redirects are disabled. The worker provides at-least-once attempts: after a crash between remote acceptance and local commit, the receiver must deduplicate. There is no claim of exactly-once delivery across a generic webhook.

### Transportation comparisons

Transport observations accept `live_quote`, `published_fare`, `estimate`, or `unavailable`, with source, currency, observation time and freshness limit. Compare known ride price, fees, tolls, parking and return cost, plus pickup/parking/walking duration. Passenger, luggage and child-seat sufficiency must be known when required. Missing capacity/time data stays explicit. Different currencies are never ranked as equivalent amounts.

Attach supplied observations under a transfer's `transport_options`, with optional `party`. Configuring a selected mode and its transfer durations replans the departure. The comparison engine does not claim live Uber/Lyft/taxi inventory. A live quote adapter and provider-specific handoff links remain integration work; no provider prices are synthesized. Google Routes supplies driving duration, not rideshare pickup availability or fare data.

## Validation and activation boundary

Run `PYTHONPATH=src python3 -m unittest discover -s tests -v`. Synthetic coverage includes timezone/overnight rendering, DST ambiguity, hotel checkout dates, duplicate/conflicting revisions, cancellation, conservative routing failure, source-labeled pricing, capacity limits, stale quotes, pending-alert invalidation, recipient revocation, delivery retry/restart, two local workers, canonical edit/concurrency conflicts, and read-only mailbox intake.

Production activation still requires the deployed credentials and canonical category/target bindings, a proven receiver/channel, a supervised worker with monitoring, and an authorized canary/readback. Live routing calls, real calendar writes, notification delivery, HTML/PDF extraction, flight-status polling, quote-provider access, unified HOUSE delivery receipts, and multi-host authorization have not been validated by synthetic tests. Private email validation is performed outside the repository; public fixtures and evidence contain only fabricated data.

Primary adapter references:

- [Google Routes computeRoutes](https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRoutes)
- [Google Calendar event deletion](https://developers.google.com/workspace/calendar/api/v3/reference/events/delete)
- [Gmail messages](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages)
- [Gmail attachments](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages.attachments)
- [PostgREST return representations](https://docs.postgrest.org/en/stable/references/api/preferences.html)
