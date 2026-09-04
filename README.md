# Household OS

A public reference architecture for a provider-neutral, agent-assisted household operating system.

**This repository contains structure and function only. It must never contain real household data.**

## Purpose

Household OS is a deployment and application layer that consumes sovereign memory and custody capabilities without redefining them. It coordinates household work, events, projects, agents, and provider integrations while preserving explicit authority and privacy boundaries.

This repository is intentionally separate from:

- **Sovereign Memory Protocol (SMP)** — implementation-neutral custody, provenance, authority, lifecycle, portability, and conformance semantics.
- **Sovereign Memory Core** — PostgreSQL reference implementation and adversarial/conformance harness for SMP.

Household OS is where deployment-specific behavior belongs: virtual Kanban, agent coordination, household event planning, calendar adapters, connector reconciliation, user-facing workflows, and deployment policy.

Low-friction calendar ingestion is a first-class platform capability. A household should be able to enable it during setup, upload an obviously dated image or PDF with minimal explanation, and have HOUSE normalize, deduplicate, route, and reconcile the resulting events. Optional provider calendars and household displays are delivery surfaces; HOUSE remains the canonical source.

## Public-repository rule

Allowed here:

- schemas and interfaces;
- synthetic examples and fixtures;
- generic deployment topology;
- connector contracts;
- authorization and reconciliation semantics;
- test harnesses using fabricated data;
- sanitized lessons that reproduce generically.

Never commit:

- names or identities of real household members;
- addresses, schools, employers, birthdays, schedules, travel, health, finance, or family records;
- production database identifiers, URLs, credentials, tokens, keys, account IDs, calendar IDs, or provider object IDs;
- screenshots, exports, logs, receipts, prompts, or traces containing real household content;
- copied HOUSE or VAULT records;
- private infrastructure details that are not required to explain the public architecture.

Use synthetic identifiers such as `person-1`, `agent-1`, `project-demo`, and `calendar-demo` in examples and tests.

## System boundary

```text
SMP protocol
    ↓
Sovereign Memory Core or another conforming runtime
    ↓
Household OS
    ├── people / roles / authority
    ├── projects
    ├── virtual Kanban / work items
    ├── events and planning
    ├── agent coordination
    ├── provider reconciliation
    └── connector adapters
            ├── calendars
            ├── household displays
            ├── mail
            ├── school / travel sources
            └── future providers
```

Dependencies run downward. Household OS may expose a deployment defect that should be reproduced generically in Core or Protocol, but deployment-specific policy must not leak upward into SMP.

## Core design rule

Memory answers **what is known and under what authority**.

Household OS answers **what is happening, what needs to happen, who is involved, and what external systems reflect that state**.

Agent conversations are not the primary coordination primitive. Shared work objects, events, decisions, evidence references, and append-only activity are.

## Architecture documents

- [`docs/IMAGE_CALENDAR_INTAKE.md`](docs/IMAGE_CALENDAR_INTAKE.md) — low-context artifact intake, setup options, category routing, provider delivery, and reconciliation.
- [`docs/PLANNING_WORK_PLANE.md`](docs/PLANNING_WORK_PLANE.md) — virtual Kanban, work-item lifecycle, and event-linked preparation work.
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — functional milestones and acceptance gates.
- [`docs/DOGFOOD_CALENDAR_SYNC.md`](docs/DOGFOOD_CALENDAR_SYNC.md) — executable calendar reconciler setup, safety boundaries, and dogfood acceptance checks.
- [`docs/SKYLIGHT_DISPLAY_BRIDGE.md`](docs/SKYLIGHT_DISPLAY_BRIDGE.md) — official connection handoff and experimental, calendar-only display visibility reconciliation.
- [`docs/THIRD_PARTY_NOTICES.md`](docs/THIRD_PARTY_NOTICES.md) — attribution for interface research and permitted derived work.

Planned documentation also includes agent coordination, authority and approval profiles, connector contracts, and synthetic conformance fixtures.

## Status

Early implementation work. The first executable slice reconciles canonical HOUSE events to Google Calendar and records provider receipts. A tested experimental adapter can plan or apply Skylight active-calendar visibility without modifying events or unrelated calendars, but sanctioned least-privilege authentication and setup UI remain open. Low-context extraction, recurring automation, and multi-provider conformance remain planned. No production deployment or real household data is represented by this repository.
