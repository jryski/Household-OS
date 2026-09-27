# Household agent interaction contracts

> **Status:** public design note; not an enforcement milestone
> **Data rule:** synthetic structure and function only; no real household content, credentials, production grants, or HOUSE payloads
> **Scope:** household domain inside this repository
> **Related:** [`PLANNING_WORK_PLANE.md`](PLANNING_WORK_PLANE.md), [`ROADMAP.md`](ROADMAP.md), [`PROGRAM-ROLE.md`](../PROGRAM-ROLE.md)

## Purpose

This note specifies how household agents and household humans interact inside Household OS. It covers authority profiles, the split between proposal and execution, and the conceptual proposal, approval, and receipt flow recorded in HOUSE.

Agent conversations are not the primary coordination primitive. Shared work objects, events, decisions, evidence references, and append-only activity are. A chat turn becomes household coordination only after it is promoted into one of those records.

The exact household entity, observation, event, capability, and provenance model is a separate design ([issue #8](https://github.com/jryski/Household-OS/issues/8)). This note names interaction functions those records must support. It does not define that model.

## Explicit non-goals

- This is not a generic cross-program Agent-Coordination runtime. The any-agent enrollment and readiness handshake discussed in [Agent-Coordination#1](https://github.com/jryski/Agent-Coordination/issues/1) stays deferred and is not imported here.
- This is not a second authorization system. Household profiles describe intended authority. Enforced tool access belongs to User MCP (or another principal-bound data plane). Final row authorization belongs to PostgreSQL policy. Connector credentials belong to the deployment.
- No production grants, real HOUSE payloads, or credentials appear in this note. Examples use synthetic identifiers such as `agent-1`, `person-1`, and `project-demo`.
- This note does not define the household entity, observation, or provenance schema.
- This note does not specify the agent runtime, model qualification, or a parent ROUTES update in sovereign-ai-os. Those remain in their own repositories and issues.
- Landing this note does not complete roadmap milestone HOS-3.

## Coordination records

Household interaction writes durable records. A model transcript is temporary discussion until one of these exists:

| Record | Function |
|---|---|
| Work item | Household intent on a board: capture, assignment, lease, review, and accepted outcome. See [`PLANNING_WORK_PLANE.md`](PLANNING_WORK_PLANE.md). |
| Event | Canonical household time and attendance context. Related to work through an event-to-work link. The event lifecycle and the work lifecycle stay distinct. |
| Activity | Append-only account of who or what changed a work item or event, and which evidence reference supported the change. |
| Proposal | A requested change that is not yet execution. |
| Approval | A principal-bound decision on one proposal. |
| Action receipt | A record that an authorized attempt was or was not carried out, including failure. |
| External reference | A link from a canonical HOUSE object to a provider object. The provider remains authoritative only for its own object. |

`project-demo` is a synthetic project work item. Boards such as `home-maintenance` and `shared-events` are synthetic scopes from the planning plane. They are labels in this note, not a claim that those rows exist in a deployment.

## Roles and authority profiles

A profile is a named bundle of household authority: which boards and categories are visible, which verbs may be proposed, which verbs may be executed, and which verbs require a separate approval. The deployment chooses the exact profile. This note requires that the profile can express the distinctions below.

Humans and agents are different principal classes. A human profile can include approval authority. An agent profile cannot approve its own proposal, accept its own outcome as `done`, or widen its own tool surface.

Illustrative profiles, using the same distinctions as the planning plane:

| Profile | Synthetic principal | Propose | Execute | Approve protected actions |
|---|---|---|---|---|
| Adult household administrator | `person-1` | Work, events, and connector actions in household scope | Household actions the deployment profile already allows, including lease override | Yes, inside the stated scope |
| Adult member | `person-3` | Work and events on visible boards | Assigned work | Only where that member's profile includes the approval |
| Guardian | `person-4` | Work and events for guarded members on visible boards | Assigned work in that scope | Only for actions the guardian profile names |
| Child or teen member | `person-2` | Inbox capture | Claim an assigned chore | No purchase approval and no protected approval |
| Guest or caregiver | `person-5` | Inbox capture on a granted board | Explicitly assigned work on that board | No |
| Household service agent | `agent-2` | Inbox work, activity notes, draft links | Lease assigned `ready` work, heartbeat, submit for review | No |
| School/calendar synchronization agent | `agent-3` | Candidate event updates, conflict flags, delivery plans | Date reconciliation and idempotent delivery only when that connector verb is pre-authorized for this profile | No |
| Maintenance or research agent | `agent-1` | Research findings and a service-call or purchase proposal on `project-demo` | Record research on a leased item | No |

Profile rules that every later fixture must preserve:

- A lease prevents two workers from owning the same attempt. A lease is not permission.
- `ready` and `required_capabilities` are scheduling metadata. They are not an authorization boundary.
- `done` is an accepted outcome. An agent's submission lands in `review` until an authorized principal accepts it.
- Shared household records and a person's private annotations are different content. `agent-1` reading board `home-maintenance` does not reveal a private annotation.
- Child, teen, guest, and agent limits are design requirements. They are unenforced until the principal-bound data plane and database policies pass their acceptance gates.

## Propose versus execute

Proposal writes a household record that asks for a change. Execution attempts the change and writes an action receipt. The same agent may be allowed to do one and not the other.

### Kanban and work items

`agent-1` may propose:

- an inbox item on an allowed board, linked to `project-demo` when the work belongs to that project;
- a research finding, blocker, or handoff as activity on a leased item;
- a dependency or event-to-work link, left for confirmation when the link mode is `suggest`;
- a status transition into `review` after submitting a result.

`agent-1` may execute only when identity, board visibility, capability, assignment, dependency, and policy checks all permit it:

- an atomic claim of assigned `ready` work, issuing one attempt token;
- bounded heartbeats on that live lease;
- release of the lease.

`agent-1` does not execute these verbs by virtue of holding the lease:

- approving a purchase or other protected action;
- marking the item `done`;
- reading parent-private annotations;
- contacting a vendor or other connector;
- reassigning work outside assignment policy;
- overriding another worker's live lease. `person-1` may override a stale lease and must leave an audit receipt.

Event-to-work modes stay as defined in the planning plane. `off` creates no automatic work. `suggest` creates proposed work for confirmation. `auto_rules` may create work from a pre-authorized template, and protected actions inside that work remain gated.

### Events

`agent-3` may propose candidate event fields, a category, a conflict flag, or a delivery plan for `event-demo-1`. Conflicting candidates stay visible. The agent does not silently pick a winner.

Execution of an event change is limited to verbs the profile pre-authorizes. The school/calendar profile may reconcile dates and perform idempotent delivery for `calendar-demo` when that verb is already in the profile. That profile does not change household financial data, approve a purchase work item, or rewrite canonical history because a provider copy drifted.

Intake and sync agents follow the same split. An approval-required work item linked from `event-demo-1` stays unapproved until an authorized human records an approval. Completing preparation work does not complete the event. A failed provider delivery does not block HOUSE preparation work.

### Connectors

Connector verbs include delivery to a calendar or display, withdrawal of delivery, and contact with an external party such as `vendor-demo`. The default for a household agent is proposal.

```text
agent-1 proposes connector action
        ↓
proposal recorded against project-demo
        ↓
person-1 approves a single named verb and target
        ↓
execution uses the deployment-held connector credential
        ↓
action receipt appended, success or failure
```

A pre-authorized connector verb, such as idempotent date reconciliation for `agent-3`, still writes a receipt. Pre-authorization is a deployment profile rule. It is not inferred from a chat instruction, a lease, or a `ready` card.

Provider objects remain delivery or observation surfaces. HOUSE keeps canonical intent, work identity, and activity history. The connector contracts for a specific provider stay in that provider's note, including [`DOGFOOD_CALENDAR_SYNC.md`](DOGFOOD_CALENDAR_SYNC.md) and [`SKYLIGHT_DISPLAY_BRIDGE.md`](SKYLIGHT_DISPLAY_BRIDGE.md). This note does not extend those adapters.

## Proposals, approvals, and receipts in HOUSE

The names below are interaction vocabulary for reviewers and later synthetic fixtures. They are not a storage schema, not a migration, and not a HOUSE API payload.

### Proposal

```text
id                 proposal-demo-1
proposer           agent-1
target_kind        work_item | event | connector_action
target_ref         work-demo-1 | event-demo-1 | connector-demo-1
project_ref        project-demo
intended_change    structure-only description of the verb and target
evidence_refs      opaque references
status             proposed | approved | rejected | expired | superseded
```

A proposal records intent. Creating `proposal-demo-1` does not contact `vendor-demo`, does not write a provider event, and does not mark `work-demo-1` done.

### Approval

```text
id                 approval-demo-1
proposal_ref       proposal-demo-1
approver           person-1
decision           approve | reject | approve_with_limits
scope              one attempt, one named verb, one named target
```

The approver is a principal the deployment profile allows to decide that verb. `agent-1` cannot fill `approver` with itself. A sentence in chat that says the proposal is approved does not create `approval-demo-1`. An approval covers the stated scope only. It does not become a standing production grant, and it does not authorize a second target or a second verb.

`approve_with_limits` records the limits on the approval. Execution outside those limits is a new proposal.

### Action receipt

```text
id                 receipt-demo-1
requester          agent-1
executor           agent-1 or the connector worker named by policy
authorization_ref  approval-demo-1 or the pre-authorized profile verb
target_ref         connector-demo-1
result             succeeded | failed | not_attempted
external_ref       opaque provider reference when a connector write occurred
```

A receipt records an attempt. It does not promote an inference into an accepted household fact. Failure and `not_attempted` are valid receipts. A missing receipt means the attempt is not claimed.

Repeating the same authorized attempt is idempotent. A retry continues or reconciles the original effect. It does not create a second canonical work item, a second canonical event, or a second provider object for `connector-demo-1`.

### Minimal lifecycle

```text
proposed
    ├── rejected or expired → stop; receipt result not_attempted if an attempt was blocked
    └── approved
            ├── execute the named verb
            └── append receipt-demo-1
                    ├── succeeded → activity on the target; review still required before done
                    └── failed → target unchanged except for the failure activity
```

Activity on `work-demo-1` cites `proposal-demo-1`, `approval-demo-1`, and `receipt-demo-1` by reference so a later reader can answer who requested the change, who allowed it, and what was attempted.

## Boundaries with User MCP and SMP/Core

Household OS describes domain behavior. Neighboring planes keep their own authority.

### User MCP: enforced tool access

[Supabase User MCP](https://github.com/jryski/Supabase_user_MCP) (or a successor principal-bound data plane) is the intended path for a household human or agent to reach application data. This repository does not implement that path.

The required split:

- User MCP exposes a small allowlisted tool surface and preserves verified principal and client context into PostgreSQL.
- Caller-supplied labels, including the string `agent-1` in a prompt, are not identity proof.
- Row and operation decisions are enforced by database policy. A household profile in this note does not override that decision.
- Reads and writes are different authorities. A profile that may read `project-demo` does not thereby gain a write tool.
- The hosted Supabase control-plane MCP is for schema and administration. It is not the household agent credential.
- Service-role and other privileged credentials are not agent identity and are not recorded here.

This note does not register tools, mint tokens, or ship grants. Later governed writes, if they are built, consume this vocabulary through that data plane. Until those gates pass, the profiles above are specification, not enforcement.

### SMP and Core: custody and evidence

[Sovereign Memory Protocol](https://github.com/jryski/sovereign-memory-protocol) defines implementation-neutral custody, provenance, authority, lifecycle, portability, and conformance. [Sovereign Memory Core](https://github.com/jryski/sovereign-memory-core) is the PostgreSQL reference runtime and conformance harness for those semantics.

Household OS consumes that custody layer. It does not redefine what makes a claim known, how evidence is superseded, or how conformance is judged. An agent may attach opaque evidence references to a proposal or activity entry. Turning a model inference into a verified household fact requires the evidence and authority SMP already requires. The agent does not perform that promotion by writing a receipt.

Issue #8 remains the place for the household entity, observation, event, capability, and provenance model. Interaction records may point at those future objects. This note does not invent their fields.

### What stays outside the agent

- Private VAULT annotations stay in the principal's private trust domain.
- Connector secrets stay in deployment custody, outside the model context and outside this repository.
- Runtime choice and model routing stay in their own program planes. A qualified model does not gain a household verb by being qualified.

## Synthetic fixtures and acceptance checks

The checks below are the acceptance reading of this contract. They use fabricated identifiers only. They are not executable tests, and this note does not add any. HOS-3 is the milestone that must demonstrate them against a principal-bound data plane.

1. **Own proposal cannot self-approve.** `agent-1` writes `proposal-demo-1` to contact `vendor-demo` for `project-demo`. The approver field cannot be `agent-1`. No connector attempt is authorized until `person-1` records `approval-demo-1`.
2. **Inbox capture is not completion.** `agent-1` may add an inbox work item on `home-maintenance` linked to `project-demo`. The item remains out of `done` until an authorized acceptance. The agent's submission stops at `review`.
3. **Lease race is not a grant.** `agent-1` and `agent-2` attempt `work-demo-1`. One attempt token is issued. The losing attempt fails. The winning lease still does not authorize a connector write.
4. **Sync profile stays inside its verb.** `agent-3` may propose a date change for `event-demo-1` and, only when date reconciliation is pre-authorized, record a receipt for that verb. The same profile cannot approve a purchase item and cannot write a financial field.
5. **Narrow human profile.** `person-2` may capture an inbox item and claim an assigned chore. `person-2` cannot approve `proposal-demo-1`.
6. **Expired authority fails closed.** After `approval-demo-1` expires or the principal is revoked, the next attempt records `not_attempted` or `failed` and does not write a provider object.
7. **Chat is not the record.** A transcript line that says `proposal-demo-1` is approved leaves the proposal in `proposed` until `approval-demo-1` exists.
8. **Private face stays private.** A private annotation for `person-1` is not returned to `agent-1` through the household board for `project-demo`.
9. **Retry is idempotent.** Repeating the authorized attempt for `connector-demo-1` reconciles one external effect. Canonical work items and events are not duplicated. A second receipt may describe the retry; it does not create a second canonical target.
10. **Fixture hygiene.** Every identifier in this list is synthetic. The check fails if a fixture adds a real name, address, school, schedule, health or finance record, credential, calendar ID, provider object ID, or copied HOUSE or VAULT payload.

## Non-claims

- Profiles in this note are not production grants and are not currently enforced.
- Conceptual field lists are not HOUSE payloads and not a schema migration.
- HOS-3 stays `planned` until its executable gates pass.
- User MCP write and approval milestones are not claimed done by this document.
- The parent program ROUTES entry for household agent coordination is unchanged by this note.

## Related documents

- [`PLANNING_WORK_PLANE.md`](PLANNING_WORK_PLANE.md) — boards, work items, leases, event-to-work modes, and the rule that chat is not the source of truth.
- [`ROADMAP.md`](ROADMAP.md) — HOS-3 governed household execution, which this note specifies and does not complete.
- [`IMAGE_CALENDAR_INTAKE.md`](IMAGE_CALENDAR_INTAKE.md) — canonical events and the rule that intake or sync agents do not auto-approve protected work.
- [`README.md`](../README.md) — public-repository rule and system boundary.
