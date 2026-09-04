# Low-context image calendar intake

> **Status:** in-progress functional milestone; public reference architecture
> **Data rule:** synthetic structure only; no real household content

## Purpose

Household schedules often arrive as paper flyers, screenshots, school menus, PDFs, and photos pinned to a refrigerator. The useful behavior is not merely OCR. The system should recognize that an obviously dated household artifact is an **intake request** even when the human provides little or no explanatory text.

Examples include:

- school and district calendars;
- PTO or activity flyers;
- lunch menus;
- sports schedules;
- appointment sheets;
- travel itineraries;
- camp or childcare schedules;
- maintenance notices.

When the active context is Household OS and the uploaded artifact visibly contains dated household information, the default workflow is to capture structured dated observations into the household event substrate. A human should not need a magic phrase such as `add these dates` every time.

## Design goals

1. **Low-friction capture.** A photo plus minimal context is enough when intent is obvious.
2. **Structured events, not transcript blobs.** Preserve the source, but promote dates into queryable event objects.
3. **Provenance first.** Every extracted event links back to the source observation.
4. **Conflict visibility.** Do not silently choose between conflicting flyers or calendars.
5. **Deduplication.** Repeated uploads and overlapping source documents must not create duplicate calendar events.
6. **Category-driven delivery.** Store more than the household chooses to display.
7. **Provider neutrality.** Google, Outlook, Apple, Skylight, iCalendar, or another display is a delivery surface, not the canonical household source of truth.
8. **Setup, not scripting.** Enabling the feature, binding targets, and creating supported category calendars belong in the Household OS setup flow.
9. **Work-aware events.** Events can create or link preparation work without collapsing event and work lifecycles into one object.

## Architectural invariants

- HOUSE is canonical for normalized household events, evidence, delivery intent, and event-to-work relationships.
- A provider is authoritative only for provider-owned details explicitly assigned to it, such as its object version, delivery state, and provider-native presentation metadata.
- Canonical all-day dates remain dates. Provider-specific rendering fallbacks are recorded on the delivery link and never rewrite the canonical event.
- Intake and provider delivery are independently configurable. A deployment can capture events without connecting or writing to any external calendar.
- Every setup or synchronization retry is idempotent. Retrying may continue incomplete work; it must not create duplicate calendars, events, or work items.
- Disabling a route stops or withdraws delivery according to deployment policy but does not destroy the canonical event, source evidence, or activity history.

## Canonical objects

A practical implementation uses the following logical objects.

### `event_category`

Defines a stable category key, label, canonical display color, importance, and default delivery preferences.

Synthetic examples:

```text
school.no_school
school.schedule_change
school.event
school.pto_event
school.pto_meeting
school.conference
school.lunch
school.spirit_day
```

The color belongs to Household OS metadata. An adapter may map it to a provider-native color ID or to a separate provider calendar/feed.

### `ingest_source`

Represents the source artifact or observation:

```text
id
source_kind          image | pdf | email | web | manual | calendar | import
source_ref           opaque reference to the source
source_sha256        optional file/content digest
source_label         human-readable label
observed_at
document_date
parser_agent
parser_version
parse_status         parsed | needs_review | superseded | rejected
confidence
metadata
```

The public reference must never contain real uploaded files or real household source references.

### `household_event`

Represents the canonical dated item:

```text
id
identity_key         deterministic dedupe identity
title
description
category_key
start_date
end_date
start_time
end_time
all_day
timezone
location
owner
visibility
source_agent
confidence
status               active | cancelled | superseded
supersedes
metadata
```

All-day events should use date semantics rather than midnight timestamps so timezone conversion cannot move a school closure to the wrong day.

### `event_evidence`

Links one canonical event to one or more source artifacts. This is what allows a district calendar and a PTO flyer to support the same event without duplicating it.

If sources disagree, the canonical event records which source was selected and why, while the conflicting evidence remains visible.

### `calendar_target`

Represents an external delivery surface, not credentials:

```text
target_key
label
provider             google | skylight | outlook | apple | ical | other
external_calendar_ref
active
binding_state        unbound | bound | degraded | disconnected | error
managed_by_house     whether setup created or adopted this target for managed delivery
capability_ref       capability snapshot used for the current binding
metadata
```

Credentials and private topology do not belong in this public repository. Production external references belong only in the deployment store; public fixtures use synthetic values.

### `provider_capability_snapshot`

Records what a provider connection can do at setup or reconciliation time instead of assuming every connector supports the same operations:

```text
capability_ref
provider
observed_at
can_list_calendars
can_create_calendars
can_write_events
can_update_events
can_cancel_or_delete_events
can_create_true_all_day
can_set_event_color
can_set_calendar_color
can_manage_reminders
can_read_provider_changes
supports_idempotency_key
metadata
```

Capabilities can change after consent is revoked or a connector version changes. The reconciler must refresh stale snapshots and degrade visibly when a previously available capability disappears.

### `calendar_delivery_rule`

Controls which categories are eligible for each target:

```text
target_key
category_key
enabled
color_override
route_key
delivery_mode        category_calendar | shared_calendar | feed | canonical_only
metadata
```

This is the core of `store everything useful, display only what the household wants`.

### `calendar_event_link`

Tracks reconciliation with an external provider:

```text
event_id
target_key
external_calendar_ref
external_event_id
canonical_hash
provider_version
provider_hash
rendering_mode       true_all_day | same_day_2359 | timed
sync_state
last_synced_at
last_error
last_action_receipt
```

This link prevents duplicate creation, enables idempotent updates, and detects canonical changes that require re-sync.

### `event_work_link`

Links an event to planning-plane work without pretending an event is a task:

```text
event_id
work_item_id
relationship         prepares_for | required_for | reminder_for | approval_for | related
rule_ref              optional rule or template that created the link
offset                optional scheduling offset from the event
sync_policy           none | dates_only | dates_and_status
metadata
```

The planning model and lifecycle rules are defined in [`PLANNING_WORK_PLANE.md`](PLANNING_WORK_PLANE.md).

## Setup contract

Calendar ingestion is an optional setup capability, not a separate expert-run script. A deployment should expose the following provider-neutral choices; product labels may be friendlier than these logical keys.

```text
calendar.intake                    off | on
calendar.delivery                  off | on
calendar.target_strategy           per_category | shared | feed | canonical_only
calendar.category.<key>.enabled    false | true, per target
calendar.category.<key>.visible    false | true, per display target
calendar.category.<key>.queryable  false | true, per assistant target
calendar.work_linking              off | suggest | auto_rules
calendar.initial_sync              none | future | bounded_history
```

Turning intake off means uploads are not implicitly promoted into calendar candidates. Turning delivery off leaves canonical intake available. Delivery, visual display, and assistant queryability are separate choices: a category can be synchronized to a provider calendar for assistant lookup while remaining hidden on a household display. `auto_rules` may create only work allowed by configured templates and authority policy; actions requiring approval remain gated.

### Setup flow

1. Ask whether calendar intake and external delivery should be enabled. Setup must remain completable when either is off.
2. Connect the chosen provider only when delivery is enabled and capture a capability snapshot.
3. Offer `per_category` when the provider can list and create or bind calendars. Offer `shared`, `feed`, or `canonical_only` fallbacks according to actual capabilities.
4. For each enabled category, search provider calendars using a deployment-defined stable managed marker and exact configured name. Reuse a unique exact match; never create another calendar merely because setup was retried.
5. Create only missing category calendars when authorized and supported, then persist each binding and setup action receipt. If creation is unsupported, bind a selected existing target or use the configured fallback.
6. Let the household toggle delivery, display visibility, and assistant queryability per target. For displays such as Skylight, separate category calendars or feeds provide reliable calendar-level show/hide controls when event-level filtering is unavailable.
7. Configure event-to-work behavior as `off`, `suggest`, or `auto_rules`, including any category templates and approval requirements.
8. Build an initial-sync plan, show its scope, execute it through a resumable outbox, and report created, updated, skipped, review-required, and failed items.
9. Schedule ongoing reconciliation and surface degraded bindings or unresolved conflicts without blocking canonical HOUSE use.

Setup stores provider IDs only in the private deployment. This public architecture documents field shapes and synthetic examples, never real calendar names, IDs, accounts, or household data.

## Intake workflow

```text
photo / PDF / screenshot
        ↓
model vision extracts candidate dated items
        ↓
register source artifact + digest
        ↓
classify each candidate
        ↓
normalize dates / times / timezone
        ↓
dedupe against canonical events
        ↓
attach source evidence
        ↓
resolve or surface conflicts
        ↓
store canonical event
        ├── category delivery rules → provider reconciliation outbox
        │                              ↓
        │                     calendar / display targets
        │
        └── event-to-work rules → suggested or created Kanban work
```

## Intent inference rule

A low-context upload may be treated as an intake request only when intent is reasonably clear from both the artifact and the current Household OS context.

Good implicit-intake examples:

- a photographed school-year calendar;
- a menu where each row is a date and lunch;
- a sports schedule with dates and opponents;
- a flyer with one clearly labeled event date.

Do **not** auto-promote every image containing a date. A receipt date, copyright year, screenshot timestamp, or incidental date is not necessarily an event.

Ambiguous intent should remain a candidate or require human clarification rather than creating a confident canonical event.

Minimal context does not mean silent guesswork. The intake service should use artifact shape, current Household OS context, source authority, and configured confidence thresholds. It may auto-promote high-confidence, reversible event captures; low-confidence dates, destructive provider changes, and authority-sensitive actions remain reviewable. The completion response should summarize what was captured, excluded, or held for review without requiring the household to operate the pipeline manually.

## Source authority and conflicts

Authority is source-specific, not model-specific.

Synthetic example:

```text
source A: school PTO summary says winter break begins Saturday
source B: official district calendar says school recess begins Monday
```

The system may select the district calendar as the canonical school-closure range because it is the more authoritative source for district attendance, while preserving source A as conflicting evidence. It must not erase the discrepancy or pretend the sources agreed.

## Calendar filtering and Skylight

A household may want critical school closures on the family display while keeping lunch menus and minor reminders available on demand.

A reasonable default profile separates assistant-readable delivery from display visibility:

| Category | Store | Assistant-readable calendar | Household display |
|---|---:|---:|---:|
| no school / break | yes | on | on |
| early release / half day | yes | on | on |
| school event | yes | on | on |
| conferences | yes | on | on |
| optional PTO event | yes | configurable | configurable |
| PTO meeting | yes | configurable | off |
| lunch menu | yes | on when enabled | off |
| snack / spirit / fundraiser day | yes | configurable | off |

These are defaults, not policy. A deployment should let the household toggle each category per target.

Skylight supports synchronization with external calendar providers. A robust adapter should not assume arbitrary event-level color metadata is preserved end-to-end. Where category-level show/hide behavior is required, an adapter can route categories into separate selectable provider calendars/feeds and map canonical Household OS colors to the provider or display when supported.

A category toggle controls one delivery or visibility rule for one target. Enabling delivery queues eligible canonical events for synchronization. Disabling delivery prevents future delivery and applies the deployment's withdrawal policy to HOUSE-managed external copies. A visibility toggle can hide an already-delivered category on a display without withdrawing the provider event. Neither action deletes canonical events. A direct Skylight integration may implement the same contract, but a provider calendar synchronized into Skylight is still one target hop and must retain its own link and health state.

### Assistant-readable hidden calendars

Low-display-value categories can still be high-query-value data. `school.lunch`, for example, can route to a native secondary Google Calendar that is hidden by default on Skylight while remaining available to Gemini and an authorized Google Home voice assistant.

For this route:

1. HOUSE continues to own the normalized lunch event and source evidence.
2. Google delivery is enabled for the lunch category, preferably to its own native secondary calendar.
3. Skylight or another visual display leaves that category calendar hidden by default.
4. The relevant household Google account explicitly enables the additional calendar for its voice assistant and retains event read access.
5. A voice query reads the provider delivery copy; it does not make Google the canonical lunch store.

The distinction matters because Google documents secondary and shared Calendar support in [Gemini Apps](https://support.google.com/gemini/answer/15305236) and additional Google Calendar selection for [Google Home and Nest](https://support.google.com/googlehome/answer/7029002). Google Home does not support calendars imported from URLs or iCalendar feeds, so a native created or shared Google calendar is the required fallback target for that specific voice-assistant use case. Voice Match, account selection, provider settings, and provider availability remain deployment checks.

Event titles should carry enough synthetic structure for provider search, such as a category label plus the normalized meal summary. Descriptions can retain additional provider-safe details, but HOUSE remains the authoritative source when an assistant response and source evidence disagree.

## Event-to-work automation

Calendar ingestion should be able to create useful preparation work in the same transaction or workflow that accepts an event. Work creation is rule-driven and independently configurable.

Synthetic rules might express:

```text
school.event          suggest: review details 7 days before
school.conference     create: choose slot → approval: confirm booking
travel.departure      create: packing checklist → blocks: ready-to-leave milestone
home.maintenance      create: clear access area 1 day before
```

Rules may create tasks, dependencies, reminders, approvals, or other work items. Each generated item carries an `event_work_link`, rule reference, provenance, and deterministic identity so reprocessing the same event does not duplicate work. Date changes may recompute linked due dates according to each link's `sync_policy`; they must not erase completed work, accepted evidence, manual overrides, or approval history.

`suggest` places proposed work in review or inbox. `auto_rules` may create pre-authorized work but does not grant authority to spend money, contact an external party, expose private content, or approve a protected action.

## All-day and display-safe rendering

Canonical all-day events use `start_date` and `end_date` date semantics. If a provider supports true all-day events, the adapter uses that provider's all-day representation, including an exclusive next-date boundary when the API requires one. The boundary is an API encoding detail, not a timed midnight event.

If the connector cannot create true all-day events, it must render the event as a same-local-day timed representation:

```text
start: 12:00 AM in the event timezone
end:   11:59 PM on the same local date
rendering_mode: same_day_2359
```

For a multi-day event, each provider representation must preserve the intended visible date range without adding an extra display day. An adapter may use one same-day timed event per date when that is the only reliable option. It must never use a timed midnight-to-midnight fallback that causes the event to bleed into the next day on a household display. The canonical event remains all-day, and the fallback mode is recorded only in `calendar_event_link` metadata.

## Reconciliation rule

The event store is authoritative for the canonical household representation. The provider remains authoritative for provider-specific state.

### Initial sync

Initial sync is a planned, resumable reconciliation pass rather than an untracked bulk export:

1. freeze the selected targets, category toggles, time scope, and capability snapshot into a sync plan;
2. discover existing HOUSE-managed objects by stored external link, managed marker, and deterministic identity, in that order;
3. compute desired creates, updates, withdrawals, skips, and review-required conflicts without writing;
4. execute through an idempotent outbox and persist each external ID, provider version, rendering mode, and action receipt as soon as it succeeds;
5. resume only incomplete operations after interruption;
6. report the final counts and unresolved items without treating partial provider success as canonical data loss.

### Ongoing reconciliation

Outbound synchronization should be idempotent:

1. compute a canonical event hash;
2. compare with the last synchronized hash;
3. create only when no external link exists;
4. update only when canonical content changed;
5. preserve provider IDs and versions;
6. record failures without creating duplicate events on retry;
7. treat cancellation separately from destructive deletion.

When provider change reads are supported, the reconciler also records a provider hash and version. Provider-only presentation changes can remain provider-owned. A date, title, cancellation, or recurrence change that overlaps a newer canonical change becomes a conflict unless the target's authority policy assigns that field to the provider. Two-way synchronization must attach observations and queue adjudication rather than letting the same edit loop between systems.

Missing or externally deleted provider objects are not automatically evidence that the canonical HOUSE event should be deleted. Depending on policy, reconciliation recreates a HOUSE-managed delivery copy, accepts a provider-owned deletion as a cancellation observation, or requests review. The decision and resulting write receive an activity record and action receipt.

## Provider capability fallbacks

Setup and synchronization choose behavior from the latest capability snapshot:

| Missing capability | Required fallback |
|---|---|
| Cannot create secondary calendars | Bind an existing calendar, use one shared target, publish a selectable feed, or remain canonical-only. Do not block intake. |
| Cannot list or verify calendars | Require an explicit binding supplied through the deployment UI and mark it unverified until a write/read receipt succeeds. |
| Cannot create true all-day events | Use the same-local-day `12:00 AM`–`11:59 PM` representation and record `same_day_2359`. |
| Cannot preserve event-level colors or filters | Route categories to separate calendars/feeds when possible; otherwise expose HOUSE toggles and document the display limitation. |
| Assistant cannot query imported feeds | Use a native secondary or shared provider calendar when supported; otherwise mark assistant queryability unavailable while preserving display/feed delivery. |
| Cannot update events | Mark changed deliveries `needs_reconcile`; do not blindly create replacements that can duplicate events. |
| Cannot read provider changes | Operate as declared one-way delivery and use stored write receipts; do not claim two-way reconciliation. |
| Read-only or disconnected | Continue canonical intake, retain the outbox with visible degraded status, and resume after a valid binding returns. |
| Cannot manage reminders | Keep reminder intent in HOUSE or linked work and use provider defaults only when explicitly configured. |

Graceful degradation means the household can keep capturing and planning in HOUSE, can see what is and is not being delivered, and can recover after provider capability returns. It does not mean silently pretending an unsupported operation succeeded.

## Privacy rule

This public repository may contain the interface, schema shape, synthetic fixtures, and generic adapter behavior only. It must never contain real school names, household member names, schedules, uploaded images, provider calendar IDs, account identifiers, or production database references.

## Acceptance fixtures

A useful synthetic test suite should prove:

1. setup succeeds with intake and delivery disabled and requires no provider connection;
2. setup creates and binds missing synthetic category calendars when the provider supports it;
3. rerunning setup reuses exact managed bindings and creates no duplicate calendars;
4. a provider without calendar creation degrades to a supported binding or canonical-only mode with visible status;
5. one low-context photo containing ten school dates produces ten structured candidate events;
6. an equivalent PDF follows the same intake path without a special import script;
7. the same artifact uploaded twice does not duplicate events;
8. a second source supporting the same date attaches evidence instead of creating another event;
9. conflicting source dates remain visible and require deterministic source-priority or human adjudication;
10. a true all-day date survives timezone conversion unchanged;
11. a provider without all-day creation receives a same-day timed event ending at `11:59 PM`, with no next-day visual bleed;
12. lunch entries are stored and delivered to an enabled assistant-readable native calendar while remaining hidden on the default family-display target;
13. toggling lunch delivery, assistant queryability, or display visibility changes only the intended target behavior and does not delete canonical events;
14. a linked event rule creates one deterministic preparation task and does not duplicate it on reprocessing;
15. an event date change updates eligible linked due dates while preserving completed work and manual overrides;
16. an approval-required work item cannot be auto-approved by the intake or sync agent;
17. initial sync resumes after partial failure without duplicating successful writes;
18. changing an event after sync marks it eligible for update rather than duplicate creation;
19. provider and canonical edits to the same governed field produce a visible conflict rather than an update loop;
20. an assistant-route capability check rejects an imported feed when the selected voice platform requires a native calendar;
21. a failed provider retry is idempotent, and the full suite requires no real household content or production IDs.
