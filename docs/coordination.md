# Agent Coordination and Virtual Kanban

## Principle

Agents coordinate around shared work objects, not around a shared conversational transcript.

Chat may exist as commentary, but it is not the canonical representation of project state, ownership, authority, or completion.

## Work-item lifecycle

A minimal lifecycle:

```text
backlog -> ready -> in_progress -> review -> done
                    |              |
                    v              v
                 blocked      waiting_human
```

State transitions should be explicit, attributable, and append-only in activity history even when the current state is materialized for fast reads.

## Work item

A generic work item should support:

- stable identifier;
- project identifier;
- bounded objective;
- current lifecycle state;
- priority or ordering policy;
- human assignees;
- agent assignees;
- subscribers/watchers;
- dependencies and blockers;
- requested review role;
- authority requirement;
- due/review timing;
- evidence/artifact references;
- current summary;
- activity/event stream.

## Coordination events

Coordination is represented as typed events attached to work or projects. Example event types:

- `work_created`
- `work_claimed`
- `work_updated`
- `work_blocked`
- `work_unblocked`
- `review_requested`
- `review_completed`
- `human_decision_required`
- `human_decision_recorded`
- `evidence_attached`
- `dependency_added`
- `handoff_requested`
- `handoff_accepted`
- `work_completed`

Free-form comments may accompany events, but typed state remains machine-readable.

## Agent identity

Every agent action should distinguish:

- represented principal;
- steward/runtime identity;
- agent identity;
- acting model/provider when relevant;
- task/project scope;
- authority basis;
- correlation/session identifiers where useful.

An agent claim is not automatically a principal decision.

## Project membership

Agents and humans may participate in projects with explicit roles such as:

- owner;
- participant;
- worker;
- reviewer;
- observer.

Project membership controls visibility and notification scope. It does not override restricted-domain access controls.

## Periodic reconciliation

Periodic agent sync is a reconciliation operation over shared state, not a meeting transcript.

A reconciliation pass may identify:

- assigned work with no recent progress;
- blocked items whose dependency is complete;
- reviews awaiting action;
- conflicting updates;
- unanswered handoff requests;
- work waiting for human authority;
- approaching deadlines;
- completed external activity not yet reflected in canonical state.

The result should be a delta: changed items, conflicts, requests, and required actions.

## Suggested cadence semantics

Cadence is deployment policy, not protocol. A deployment may use:

- lightweight frequent reconciliation for changed work;
- project-specific reconciliation when subscribed objects change;
- periodic broader review for stale work and unresolved conflicts;
- immediate escalation for explicitly configured high-priority conditions.

No cadence is normative in this repository.

## Human authority

A model or agent may recommend, prepare, or report a decision. Authority-bearing state changes require the configured authority basis.

Examples:

- agent recommendation -> proposal;
- verified principal approval -> decision;
- external provider observation -> observation;
- peer reviewer conclusion -> review result.

These are separate object/event types and must not be collapsed into one status field.
