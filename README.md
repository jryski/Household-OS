# Household OS

A public reference architecture for a provider-neutral, agent-assisted household operating system.

**This repository publishes reusable implementation code and synthetic examples. Real household data and deployment credentials must remain private.**

## Implemented calendar delivery

The repository includes runnable connector code alongside synthetic examples.
The server-side worker reads pending canonical deliveries from the Supabase
outbox, writes Google Calendar events, and records success or failure receipts.

- [Google adapter](src/household_os/google_calendar.py): derives a stable event
  ID from the delivery target and canonical event ID; retries reuse that ID.
- [Outbox repository](src/household_os/supabase_store.py): reads pending
  deliveries and records results through fixed database functions.
- [Command-line entry point](src/household_os/cli.py): separates planning from
  live synchronization; external writes require `sync --live`.
- [Calendar delivery runbook](docs/DOGFOOD_CALENDAR_SYNC.md): prerequisites,
  credential alternatives, bounded canary steps, and acceptance checks.

Google HTTP execution and database receipt persistence are separate operations.
Stable IDs support retry recovery; they do not establish a transaction across
both systems, complete concurrent-worker safety, or continuous operation.

### Integration paths and requirements

| Path | Requirements and scope |
| --- | --- |
| Synthetic tests and examples | Fabricated data and injected test dependencies; real household records and provider credentials stay outside the public test corpus. See [tests](tests/). |
| Supabase + Google Calendar delivery | A prepared canonical event/delivery schema and server-side Supabase service credential, plus either a short-lived Google access token or Google client ID, client secret, and refresh token. See the [runbook](docs/DOGFOOD_CALENDAR_SYNC.md). |
| Optional Skylight visibility bridge | A separate experimental path with a short-lived revocable Skylight token after the official calendar connection. It changes calendar visibility, not event content. Google delivery does not require this token. See the [bridge guide](docs/SKYLIGHT_DISPLAY_BRIDGE.md). |

The delivery worker uses server-side service authority. It does not establish
caller-scoped agent write authorization or the planned proposal/approval
enforcement. Sanctioned least-privilege Skylight authentication, repeatable
end-to-end setup, and continuous-operation acceptance remain open.

## Orientation: purpose, place and first test

A short map for people and AI assistants arriving here first. Each row links
the source that supports it.

| Question | Answer |
| --- | --- |
| What is this? | The household application layer: events, planning, agent coordination and provider reconciliation. The first executable slice reconciles canonical household events to Google Calendar and records provider receipts ([purpose](#purpose), [status](#status)). |
| Where does it fit? | A household-domain application in the [Sovereign AI OS program map](https://github.com/WireSpeedComputing/sovereign-ai-os) ([component routes](https://github.com/WireSpeedComputing/sovereign-ai-os/blob/main/ROUTES.md), [program role](PROGRAM-ROLE.md)). It consumes memory and custody capabilities without redefining them. [Sovereign Vault](https://github.com/WireSpeedComputing/Sovereign-Vault) is a separate business application with its own records and permissions; it is not the principal-private VAULT trust domain named in [PROGRAM-ROLE.md](PROGRAM-ROLE.md#privacy-boundary). No install order across components is implied. |
| What is supported today? | Early implementation. Live delivery needs a prepared Supabase schema, a server-side service credential and Google credentials ([runbook prerequisites](docs/DOGFOOD_CALENDAR_SYNC.md#prerequisites)). The base event, target, link and outbox tables are described in [IMAGE_CALENDAR_INTAKE.md](docs/IMAGE_CALENDAR_INTAKE.md); the migrations here add only the worker receipt and lunch-query functions ([supabase/migrations](supabase/migrations)). |
| First test (no provider) | The [provider-free sample route](docs/DOGFOOD_CALENDAR_SYNC.md#start-without-a-provider-fabricated-sample-data) runs the reconciliation code over [fabricated outbox rows](tests/fixtures/calendar_sample_outbox.json) with in-memory stand-ins: after `pip install .` ([pyproject.toml](pyproject.toml)), run `python -m unittest -v tests.test_calendar_sample_fixture`. It covers planning, a one-item canary, failure isolation and retry, idempotent rerun, in-place update, lost-receipt recovery and input rejection. The CLI itself has no provider-free mode: `sync` refuses to run without `--live`, and `plan` needs the server-side environment ([cli.py](src/household_os/cli.py), [supabase_store.py](src/household_os/supabase_store.py)). |
| Provider-connected trial | A separate operator path with its own isolated calendar, credentials and explicit authorization ([runbook](docs/DOGFOOD_CALENDAR_SYNC.md), [Skylight bridge](docs/SKYLIGHT_DISPLAY_BRIDGE.md)). |
| Prerequisites and exact commands | Git and Python 3.11 or later; no database, Google account or credential. From a clean disposable checkout: `python -m venv .venv`, activate it (`. .venv/bin/activate`, or `.venv/Scripts/Activate.ps1` on Windows), `python -m pip install .`, `python -m unittest -v tests.test_calendar_sample_fixture` (10 tests), then `python -m unittest discover -s tests -v` (29 tests, the full component suite). |
| Expected results | Allowed: planning makes no provider call; a one-item canary creates one event; reruns create nothing; a canonical change updates the same event; a lost receipt is recovered through the stable event ID without a duplicate. Denied: invalid canonical rows are rejected before any provider call, and an injected provider failure stays isolated and retryable. Summaries carry counts only. |
| Cleanup | The sample creates no provider events or database records. Deactivate the virtual environment and delete the disposable checkout. |
| Evidence | Code and synthetic tests in this repository. The [unit-test workflow](.github/workflows/unit-tests.yml) installs the package into a fresh virtual environment and runs the sample and the full component suite on every pull request and on `main`, failing on any skip. The [leak gate](.github/workflows/leak-gate.yml) scans changes. |
| Scope of the sample | The sample uses an **in-memory outbox** that follows the runbook's pending rule, and a **fake provider**. It establishes the reconciliation logic only. It does not establish the deployed `calendar_delivery_outbox` view, live SQL integration, Google delivery, continuous service, automatic source extraction or the morning experience. |
| Source status | Merged on `main`: the calendar reconciler, store, Google adapter, display bridge and their unit tests. Under review: the provider-free sample and its CI (this change, until merged). Operating observation: the [roadmap checkpoint](docs/ROADMAP.md#implementation-checkpoint) records live canary and bulk reconciliation in the project's own deployment. That is an observation, not a continuous-operation or general-setup claim. Future direction: low-context artifact intake, event-to-work automation and connector conformance (HOS-1 and HOS-2 in the [roadmap](docs/ROADMAP.md)). |
| Limitations | Low-context extraction, recurring automation and multi-provider conformance are planned; least-privilege Skylight authentication and setup UI are open ([status](#status)). |
| Contribute | [CONTRIBUTING.md](CONTRIBUTING.md) (issue first, synthetic data only), DCO sign-off ([DCO.md](DCO.md)). |
| License and security | Apache-2.0 ([LICENSE](LICENSE), [NOTICE](NOTICE)). Report vulnerabilities privately through this repository's [private reporting form](https://github.com/jryski/Household-OS/security/advisories/new), with the email fallback in [SECURITY.md](SECURITY.md). Never post household data or exploit details publicly. |
| Related components | [Supabase User MCP](https://github.com/jryski/Supabase_user_MCP) (principal-bound access before multi-principal use is trusted), [Sovereign Memory Core](https://github.com/jryski/sovereign-memory-core), [Sovereign Memory Protocol](https://github.com/jryski/sovereign-memory-protocol). No other component is a prerequisite for the unit tests above; adopt components independently and in any order. |

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
- [`docs/AGENT_INTERACTION_CONTRACTS.md`](docs/AGENT_INTERACTION_CONTRACTS.md) — household-scoped agent roles, propose-versus-execute boundaries, and conceptual proposals, approvals, and receipts.
- [`docs/ROADMAP.md`](docs/ROADMAP.md) — functional milestones and acceptance gates.
- [`docs/DOGFOOD_CALENDAR_SYNC.md`](docs/DOGFOOD_CALENDAR_SYNC.md) — executable calendar reconciler setup, safety boundaries, and dogfood acceptance checks.
- [`docs/SKYLIGHT_DISPLAY_BRIDGE.md`](docs/SKYLIGHT_DISPLAY_BRIDGE.md) — official connection handoff and experimental, calendar-only display visibility reconciliation.
- [`docs/THIRD_PARTY_NOTICES.md`](docs/THIRD_PARTY_NOTICES.md) — attribution for interface research and permitted derived work.

Planned documentation also includes connector contracts and broader synthetic conformance fixtures. Household agent coordination and authority and approval profiles are specified in [`docs/AGENT_INTERACTION_CONTRACTS.md`](docs/AGENT_INTERACTION_CONTRACTS.md). Enforcement of those profiles remains the HOS-3 milestone.

## Status

Early implementation work. The first executable slice reconciles canonical HOUSE events to Google Calendar and records provider receipts. A tested experimental adapter can plan or apply Skylight active-calendar visibility without modifying events or unrelated calendars, but sanctioned least-privilege authentication and setup UI remain open. Low-context extraction, recurring automation, and multi-provider conformance remain planned. No production deployment or real household data is represented by this repository.

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) and
[NOTICE](NOTICE). Contributions are accepted under the Developer Certificate of
Origin. See [DCO.md](DCO.md).
