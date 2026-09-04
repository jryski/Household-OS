# Household OS Architecture

## Scope

Household OS is the deployment and application layer above a sovereign memory/custody substrate. It organizes household work, events, projects, provider observations, and agent collaboration without becoming the protocol itself.

## Layers

### 1. Protocol layer

Defines implementation-neutral semantics for custody, provenance, authority, lifecycle, supersession, portability, erasure, and conformance.

Household OS consumes these semantics. It does not redefine them.

### 2. Runtime layer

Provides a concrete implementation of protocol semantics, such as a PostgreSQL reference runtime.

Household OS depends only on documented runtime contracts, not on deployment-specific database internals.

### 3. Household OS layer

Owns deployment-specific domains:

- people and roles;
- projects;
- work items and Kanban state;
- household events and planning;
- agent subscriptions, assignments, and review;
- provider observations and reconciliation;
- connector adapters;
- human approval workflows;
- household-specific policy configuration.

### 4. External provider layer

Examples include calendar providers, household displays, mail systems, school information sources, travel providers, files, and future home systems.

Provider state is not automatically canonical state.

## Canonical domains

### People and roles

Represents principals, household membership, agents, service identities, roles, and scoped authority.

A relationship does not imply unrestricted access. Authority is explicit and capability-scoped.

### Projects

A project is a durable collaboration boundary with participants, goals, status, work items, events, decisions, evidence references, and subscriptions.

### Work

The primary coordination primitive is the work item, not chat.

A work item may contain:

- title and bounded objective;
- lifecycle state;
- human and agent assignees;
- watchers/subscribers;
- dependencies;
- due or review timing;
- authority requirement;
- evidence references;
- append-only activity.

### Events

A canonical event represents a household-relevant occurrence independently from any one provider's event object.

Provider event IDs belong in adapter/link records.

### Decisions

A decision records an authority-bearing outcome separately from discussion, recommendation, or model inference.

### Provider observations

An observation captures what an external system reported at a point in time. Observation does not equal authority.

## Dependency rule

```text
protocol -> runtime -> Household OS -> provider adapters
```

Lower layers must not depend on household-specific policy, provider IDs, or UI assumptions.

## Defect promotion

A deployment defect discovered in Household OS remains local unless it can be reproduced generically.

- If the defect is runtime-specific, reproduce it with synthetic inputs in the runtime repository.
- If it reveals an implementation-neutral semantic ambiguity, reduce it to a protocol issue or conformance vector.
- Never move private deployment evidence into a public protocol/runtime repository.

## Non-goals

Household OS is not:

- a replacement for every calendar, mail, task, school, or travel application;
- a universal agent chatroom;
- a store for secrets or private household records in this public repository;
- a protocol specification;
- a memory retrieval engine;
- a justification for broad agent credentials.
