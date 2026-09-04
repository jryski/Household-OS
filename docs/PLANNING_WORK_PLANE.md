# Household planning and work plane

> **Status:** public reference architecture  
> **Data rule:** synthetic structure only; no real household content  
> **Shared program context:** [`Sovereign AI OS`](https://github.com/jryski/sovereign-memory-core/blob/main/docs/ecosystem/SOVEREIGN_AI_OS.md)

## Purpose

Household planning is more than a calendar and more than a task list. It is the durable coordination layer for what the household intends to do, who is involved, what must happen first, what external systems reflect the plan, and what actually happened.

The same planning kernel is useful in a business deployment. Household OS owns the household-specific profile, not the universal concept.

## Household jobs

A household board should be able to coordinate:

- family projects;
- school dates, forms, assignments, and activities;
- shared events and preparation;
- chores, routines, and age-appropriate responsibilities;
- home maintenance and repairs;
- purchases, errands, and waiting-for-delivery work;
- travel preparation;
- recurring administrative work;
- agent research, proposals, and approved actions.

## Core objects

A practical implementation needs more than one `tasks` table.

### Board

Defines the planning scope, visibility, ownership domain, lifecycle, policy reference, and source-of-truth behavior.

Example synthetic boards:

```text
family-projects
school-and-activities
shared-events
home-maintenance
chores-and-routines
errands-and-purchases
```

### Work item

Represents an epic, project, task, research item, decision, milestone, event, bug, or note. It should support:

- stable opaque identity and human-readable key;
- title, description, acceptance criteria, and deliverable;
- status, priority, ordering, due time, and not-before time;
- parent/child structure;
- household workstream and location or entity references;
- human and agent assignment;
- authority and review requirements;
- source, confidence, evidence, and external references;
- result, resolution, and correction history.

### Dependency

Expresses blocking, related, duplicate, or other explicit relationships between work items. Dependencies prevent an agent from treating a high-priority card as executable before its prerequisites are satisfied.

### Activity

Preserves creation, assignment, claim, heartbeat, progress, finding, blocker, handoff, submission, review, completion, cancellation, and synchronization events.

Activity is not merely UI history. It is how the household can answer, "Why did this change, who or what changed it, and what evidence supported the change?"

### External reference and synchronization state

Links a canonical household work item to Google Calendar, Skylight, school systems, email threads, orders, tickets, or another provider object without making that provider the entire household source of truth.

### Event-to-work link

Links a canonical event to preparation or follow-up work while preserving their separate identities and lifecycles:

```text
event_id
work_item_id
relationship         prepares_for | required_for | reminder_for | approval_for | related
rule_ref              optional event-work rule or template
offset                optional due/not-before offset from event time
sync_policy           none | dates_only | dates_and_status
last_derived_hash
metadata
```

A deterministic identity derived from the event, rule, and template prevents duplicate tasks when an artifact is reprocessed or provider synchronization retries.

## Lifecycle

A useful default lifecycle is:

```text
inbox → backlog → ready → in_progress → review → done
                       ↘ blocked
```

`cancelled` preserves abandoned work without deleting history.

- **Inbox:** captured but not yet understood.
- **Backlog:** valid work that is not yet sequenced or sufficiently prepared.
- **Ready:** scoped, unblocked, and eligible for an authorized worker.
- **In progress:** actively owned or leased.
- **Blocked:** waiting on an explicit condition.
- **Review:** result submitted and awaiting an authorized decision.
- **Done:** accepted outcome, not merely an agent's assertion of completion.

## Human and agent work

Agents should lease work rather than silently assign it to themselves.

An agent claim should be atomic, issue a unique attempt token, expire, support bounded heartbeats, preserve attempt history, and fail after release, revocation, reassignment, completion, or reclaim by another worker.

A lease prevents duplicate work. It does not grant permission.

An agent may claim only when trusted identity, board visibility, capability, assignment, dependency, and policy checks permit it. A card's `ready` status or `required_capabilities` field is scheduling metadata, not an authorization boundary.

## Household authority examples

The exact policy belongs to the deployment, but a profile should support distinctions such as:

- adult household administrator;
- adult member;
- guardian;
- child or teen member;
- guest or caregiver;
- household service agent;
- school/calendar synchronization agent;
- maintenance or research agent.

Possible outcomes include:

- a child can create an inbox item but cannot approve a purchase;
- a teen can claim an assigned chore but cannot read parent-private annotations;
- an event-sync agent can reconcile dates but cannot change household financial data;
- a maintenance agent can propose a service call but requires approval before contacting a vendor;
- an adult can override a stale lease while preserving an audit receipt.

These examples are not enforced until the principal-bound data plane and database policies pass their acceptance gates.

## Shared and private faces

The shared household store may know that a device, school event, project, or assigned responsibility exists. A person's private notes, concerns, interpretation, or sensitive records belong in that person's private trust domain.

This is not "one shared row with hidden columns." The shared and private faces are different content with different authority and lifecycle.

Cross-domain computation, when authorized, should be purpose-bound and ephemeral. It should not silently copy private records into the shared board.

## Events versus work

A calendar event and a work item are related but not identical.

```text
Event: school concert at 19:00
Work: buy required clothing
Work: arrange transportation
Work: submit participation form
Work: charge camera
```

The event supplies time and attendance context. The planning plane tracks preparation, dependencies, responsibility, completion, and evidence.

### Link modes

Event-to-work automation is optional during setup and has three modes:

- **Off:** events do not automatically propose or create work; users may still link items manually.
- **Suggest:** matching rules create proposed work in `inbox` or `review` for confirmation.
- **Auto rules:** pre-authorized templates create work automatically, but authority and approval checks still apply to protected actions.

Rules are scoped by event category, source authority, household profile, and target board. A rule can specify:

- a task, checklist, milestone, decision, reminder, or approval item;
- due and not-before offsets relative to event start;
- parent/child and dependency relationships;
- default assignee or eligible role, without bypassing assignment policy;
- required evidence and acceptance criteria;
- whether later event date changes may update derived work dates.

### Change behavior

When an event date changes, linked incomplete work with `dates_only` or `dates_and_status` may have its derived dates recalculated. Completed work, accepted evidence, manual date overrides, and approval history are preserved. A cancelled event may cancel untouched generated work when policy allows, but in-progress or completed work is flagged for review instead of silently erased.

Changing a work item's status must not rewrite the event unless an explicit relationship and policy allows it. Completing `buy required clothing`, for example, does not complete or cancel the concert. Likewise, delivery failure to Google Calendar does not block HOUSE preparation work from proceeding.

### Event-to-work workflow

```text
canonical HOUSE event
        ↓
category + source + authority rule evaluation
        ├── no match → event only
        ├── suggest → proposed work → human review
        └── auto rule → authorized work items
                            ↓
                 dependencies / reminders / approvals
                            ↓
                    normal Kanban lifecycle
```

Every generated item records the source event, triggering rule, activity entry, and creation receipt. Re-evaluation is idempotent.

## Google Calendar and Skylight

A future adapter must explicitly define:

- canonical and external IDs;
- one-way or two-way authority;
- recurrence and exception behavior;
- create, update, cancellation, and deletion semantics;
- deduplication and loop prevention;
- reminder ownership;
- provider staleness and last-seen version;
- conflict adjudication;
- action receipts for external writes.

The safest default is that the household planning store owns work identity, dependency, review, and history, while the calendar provider remains authoritative for its provider-specific event object.

Calendar delivery is configured during Household OS setup. A deployment may enable or disable intake, delivery, per-category calendars, category routes, and event-to-work automation independently. When supported, setup creates or binds category calendars so a household display can show or hide categories. When unsupported, the adapter uses an existing shared target, feed, or canonical-only mode and reports the limitation.

Display visibility is separate from assistant queryability. A category such as lunch may be delivered to a native secondary Google Calendar for Gemini or Google Home lookup while remaining hidden by default on Skylight. The assistant reads a provider copy under its account and calendar-selection permissions; HOUSE remains canonical, and an imported iCalendar feed must not be presented as assistant-queryable when the selected voice platform does not support it.

Canonical all-day events remain date-based. A provider that cannot create a true all-day object receives a same-local-day timed representation ending at `11:59 PM`; a timed midnight-to-midnight representation is not an acceptable fallback because it can display on the following day. The full setup, fallback, initial-sync, external-ID, deduplication, and reconciliation contract is defined in [`IMAGE_CALENDAR_INTAKE.md`](IMAGE_CALENDAR_INTAKE.md).

## Source-of-truth split

- **HOUSE planning tables:** household intent, work identity, dependency, assignment, review, and accepted status.
- **Calendar or provider:** provider-specific object and delivery state.
- **Repository:** generic schema, policy, fixtures, and tests.
- **Private VAULT:** principal-private annotations and restricted personal content.
- **Chat:** temporary discussion until promoted into a card, note, decision, or accepted record.

## Initial public acceptance fixtures

A useful first fixture set should prove:

1. A school event with three preparation tasks and one blocking form.
2. A home repair with research, approval, purchase, scheduling, and completion evidence.
3. A recurring chore assigned to a child under limited authority.
4. Two agents racing to claim the same synthetic work item, with only one succeeding.
5. Lease expiry and safe reclaim by another agent.
6. A submitted result requiring adult review.
7. A calendar conflict that remains visible instead of silently choosing a side.
8. A private annotation that cannot be retrieved through the household board.
9. Revoked or expired agent access failing closed.
10. A provider synchronization retry that is idempotent and does not create a duplicate event.
11. A low-context calendar artifact creating a canonical event and one linked preparation task under a synthetic rule.
12. Reprocessing that event without duplicating its linked task, reminder, dependency, or approval.
13. An event date change recomputing eligible open-work dates while preserving a completed task and a manual override.
14. A cancelled event routing active linked work to review instead of silently deleting it.
15. Calendar delivery being disabled while canonical events and linked Kanban work remain available.

## Relationship to the current build board

The private Sovereign AI OS program board in Jesse's Vault is a live build-plane implementation of these general mechanics. Its database rows and real project state do not belong in this public repository.

Portable lessons may be reproduced here only as generic schema, synthetic fixtures, tests, and sanitized design decisions.
