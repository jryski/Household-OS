# Household OS

A public reference architecture for a provider-neutral, agent-assisted household operating system.

**This repository contains structure, contracts, and synthetic examples only. It must never contain real household data.**

## Purpose

Household OS is a deployment/application reference layer in the broader Sovereign Memory program. It consumes provenance, custody, authority, identity, and bounded-capability primitives without redefining them.

It coordinates household work, projects, events, agents, connectors, and user-facing workflows while preserving explicit authority and privacy boundaries.

## Program relationship

Household OS is intentionally separate from:

- **Sovereign Memory Protocol (SMP)** — implementation-neutral provenance, custody, authority, lifecycle, verification, portability, conformance, and claim semantics.
- **Sovereign Memory Core** — PostgreSQL reference implementation and adversarial/conformance runtime for SMP semantics.
- **Supabase User MCP** — bounded authenticated application-data capability for user/agent access through Supabase and RLS.
- **Private household deployment authority** — real topology, credentials, operational receipts, recovery evidence, and household-specific policy.

Dependencies run one way: deployments/applications consume protocol/runtime/capability primitives. Deployment policy must not leak upward and become protocol by accident.

## System boundary

```text
SMP protocol
    ↓
reference runtime / conforming implementation
    ↓
verified identity + bounded data capability
    ↓
Household OS application layer
    ├── people / roles / authority
    ├── projects and work items
    ├── events and planning
    ├── agent coordination
    ├── provider reconciliation
    └── connector adapters
```

A repository, deployment, store, trust domain, and visibility class are different things. Public Household OS is not the private operational deployment.

## Relationship to emerging agent-access work

SMP is evaluating an **Agent Access Integrity Boundary** concept for introducing agents to existing systems of record in situ: observe and commit a protected T0 surface before agent access, then evaluate post-T0 change/attribution under explicit assurance limits.

Household OS may eventually consume such a profile for connectors or legacy household data sources. It does not define or certify that protocol concept itself.

Similarly, **Governed Artifact Inspection** is being designed in the user-context MCP lane so agents can inspect durable artifacts through opaque IDs and bounded RLS-enforced capability rather than generic Storage access. Household OS may consume that capability once its identity and security gates are satisfied.

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
- copied private deployment records;
- private infrastructure details that are not required to explain the public architecture.

Use synthetic identifiers such as `person-1`, `agent-1`, `project-demo`, and `calendar-demo` in examples and tests.

## Core design rules

- Memory/custody systems answer **what is known, where it came from, and under what authority**.
- Household OS answers **what is happening, what needs to happen, who is involved, and what external systems reflect that state**.
- Authentication and authorization are separate from provenance labels: `agent-1` is not proof of identity.
- RLS/policy-derived visibility must come from a verified user context; privileged backend credentials are maintenance paths, not evidence of user authorization.
- Agent conversations are not the primary coordination primitive. Shared work objects, events, decisions, evidence references, and append-only activity are.

## Documentation direction

This public repository should grow only sanitized, portable material for:

- architecture and domain boundaries;
- project/work-item lifecycle;
- agent coordination and reconciliation;
- event/calendar canonical models;
- connector observation/reconciliation contracts;
- authority and approval semantics;
- authenticated user-capability integration;
- public-repository privacy and synthetic-fixture policy.

Private deployment evidence should be promoted here only as fresh sanitized architecture commits, never by changing a private repository's visibility.

## Status

Early public reference architecture. No production deployment, real household data, protocol-conformance claim, or private operational acceptance is represented by this repository.
