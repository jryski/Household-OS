# Low-context image calendar intake

> **Status:** public reference architecture  
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
metadata
```

Credentials and private topology do not belong in this public repository.

### `calendar_delivery_rule`

Controls which categories are eligible for each target:

```text
target_key
category_key
enabled
color_override
route_key
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
sync_state
last_synced_at
last_error
```

This link prevents duplicate creation, enables idempotent updates, and detects canonical changes that require re-sync.

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
        ↓
category delivery rules
        ↓
provider reconciliation outbox
        ↓
Google / Outlook / Apple / Skylight / iCal
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

A reasonable default profile is:

| Category | Store | External calendar default |
|---|---:|---:|
| no school / break | yes | on |
| early release / half day | yes | on |
| school event | yes | on |
| conferences | yes | on |
| optional PTO event | yes | configurable |
| PTO meeting | yes | off |
| lunch menu | yes | off |
| snack / spirit / fundraiser day | yes | off |

These are defaults, not policy. A deployment should let the household toggle each category per target.

Skylight supports synchronization with external calendar providers. A robust adapter should not assume arbitrary event-level color metadata is preserved end-to-end. Where category-level show/hide behavior is required, an adapter can route categories into separate selectable provider calendars/feeds and map canonical Household OS colors to the provider or display when supported.

## Reconciliation rule

The event store is authoritative for the canonical household representation. The provider remains authoritative for provider-specific state.

Outbound synchronization should be idempotent:

1. compute a canonical event hash;
2. compare with the last synchronized hash;
3. create only when no external link exists;
4. update only when canonical content changed;
5. preserve provider IDs and versions;
6. record failures without creating duplicate events on retry;
7. treat cancellation separately from destructive deletion.

## Privacy rule

This public repository may contain the interface, schema shape, synthetic fixtures, and generic adapter behavior only. It must never contain real school names, household member names, schedules, uploaded images, provider calendar IDs, account identifiers, or production database references.

## Acceptance fixtures

A useful synthetic test suite should prove:

1. one photo containing ten school dates produces ten structured candidate events;
2. the same photo uploaded twice does not duplicate events;
3. a second source supporting the same date attaches evidence instead of creating another event;
4. conflicting source dates remain visible and require deterministic source-priority or human adjudication;
5. an all-day date survives timezone conversion unchanged;
6. lunch entries are stored but excluded from the default family-display target;
7. toggling the lunch category causes those events to enter the synchronization outbox;
8. changing an event after sync marks it eligible for update rather than duplicate creation;
9. a failed provider retry is idempotent;
10. no real household content is required to run the test suite.
