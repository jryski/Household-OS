# Household OS roadmap

> **Status:** public planning document
> **Data rule:** synthetic structure only; no real household content or production identifiers

## Roadmap principles

Household OS milestones are accepted through observable behavior and synthetic fixtures, not through screenshots of a private deployment. HOUSE owns canonical household intent and history. Calendar, display, mail, and other providers are delivery or observation surfaces with explicitly bounded authority.

Milestone status values are `foundation`, `planned`, `in_progress`, `acceptance`, and `complete`. A milestone is not `complete` until its documented acceptance gates pass.

## Milestones

| Milestone | Status | Outcome |
|---|---|---|
| HOS-0: public architecture baseline | foundation | Define repository boundaries, privacy rules, canonical events, and the planning/work plane. |
| HOS-1: low-friction calendar ingestion and delivery | in_progress | Turn dated images, PDFs, and similar artifacts into canonical HOUSE events; configure provider delivery during setup; reconcile without duplicates; connect events to preparation work. |
| HOS-2: synthetic connector conformance | planned | Exercise provider capability negotiation, retries, conflicts, recurrence, cancellations, and display-specific routing with fabricated fixtures. |
| HOS-3: governed household execution | planned | Enforce principal-bound authority, approvals, agent leases, and action receipts across shared events and work. |

## HOS-1: low-friction calendar ingestion and delivery

### Functional scope

HOS-1 makes calendar ingestion part of normal setup and daily use rather than a one-off import procedure.

- Setup can enable or disable calendar intake, provider delivery, per-category calendars, and event-to-work automation independently.
- When the connected provider supports it, setup discovers exact existing category calendars, reuses them, and creates and binds only missing calendars.
- When category calendars are not supported, setup offers the best supported target strategy without blocking canonical intake.
- Each category can be enabled or disabled per target so displays such as Skylight can expose useful show/hide controls.
- Delivery, assistant queryability, and visual visibility are independent: a lunch calendar can remain hidden on Skylight while a native provider calendar supplies the same events to Gemini or Google Home.
- An uploaded image, PDF, screenshot, or other clearly dated artifact can become structured candidate events with minimal conversational context.
- HOUSE normalizes dates and times, records source evidence, deduplicates repeated or overlapping input, and surfaces ambiguous or conflicting evidence.
- Initial synchronization and ongoing reconciliation use stable external references, hashes, provider versions, and idempotent retries.
- True provider all-day events are preferred. If a provider cannot create them, the fallback is a same-local-day timed event ending at `11:59 PM`, never a midnight-to-midnight timed event that visually bleeds into the next day.
- Events can spawn or link preparation tasks, dependencies, reminders, approvals, and other Kanban work under deployment-defined rules.
- Disabling delivery or a category route does not delete the canonical HOUSE event or its provenance.

### Implementation checkpoint

The first executable dogfood slice is delivered:

- a server-side reconciler reads the canonical delivery outbox and writes idempotent Google Calendar events;
- provider success and failure receipts update external links atomically;
- true all-day and same-day `11:59 PM` rendering modes are implemented and tested;
- the lunch route is assistant-queryable while remaining display-hidden by default;
- authorized agents have a canonical HOUSE lunch query independent of Google;
- provider IDs are deterministic in the direct adapter, retries are bounded, and command output omits household content;
- the deployed schema and worker have passed local tests, live canary/bulk reconciliation, and security/performance review.

Low-context image/PDF extraction, setup UI, automated provider-calendar creation, recurring worker execution, event-to-Kanban generation, and multi-provider conformance remain in progress. This checkpoint is not milestone completion.

### Required development contracts

The milestone depends on public, provider-neutral contracts for:

1. setup choices and feature flags;
2. provider capability discovery and binding results;
3. canonical event, source evidence, delivery rule, and external-link records;
4. initial-sync planning and resumable execution;
5. periodic reconciliation and conflict review;
6. all-day and same-day timed fallback rendering;
7. event-to-work links and rule-driven work templates;
8. action receipts and synthetic conformance fixtures.

### Acceptance gates

HOS-1 reaches acceptance only when synthetic tests demonstrate that:

1. a new deployment can leave calendar ingestion off and complete setup without a provider connection;
2. an enabled deployment can create or bind category calendars automatically where the provider permits it;
3. an existing exact binding is reused and setup retries do not create duplicate calendars;
4. unsupported calendar creation degrades to binding, a shared target, a feed/export target, or canonical-only mode with a visible status;
5. category toggles control delivery independently without removing canonical events;
6. a synthetic lunch category can be delivered to an assistant-readable native calendar while remaining hidden by default on the household display;
7. a low-context image or PDF produces structured candidate events linked to source evidence;
8. repeated uploads and overlapping sources do not duplicate canonical or provider events;
9. a true all-day event preserves its canonical date across timezone conversion;
10. a provider without all-day creation receives a same-day timed representation ending at `11:59 PM` local time;
11. initial sync can resume after partial failure without duplicating external events;
12. ongoing changes, cancellations, provider edits, stale versions, and conflicts follow documented authority rules;
13. every external write records its target, external ID when available, canonical hash, sync state, and action receipt;
14. an event can create or link preparation work with dependencies, reminders, and an approval gate without conflating event and work lifecycles;
15. disabling the feature or disconnecting a provider leaves HOUSE records queryable and reconcilable;
16. the entire fixture suite uses synthetic data and contains no production calendar or household identifiers.

## HOS-2 preview: connector conformance

HOS-2 turns the HOS-1 contracts into reusable adapter tests. It should include capability matrices for at least one full calendar API, one limited/read-only integration, one calendar-feed export, and one household display reached through a calendar provider. The tests must exercise recurrence exceptions, provider rate limits, revoked access, retry backoff, loop prevention, and external deletion or drift.

## HOS-3 preview: governed execution

HOS-3 applies household authority to event-linked work. It should prove that agents and household members can capture and prepare work without silently gaining permission to contact providers, spend money, expose private annotations, approve protected actions, or mark outcomes accepted.
