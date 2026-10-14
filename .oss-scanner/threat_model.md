# OSS Scanner threat model: Household OS

This repository is a public, synthetic-only household coordination reference. It has no real household data or production deployment. The public-repository rule in [README.md](../README.md) is mandatory.

## Scope and current implementation

Focus on the implemented Python reference in `src/household_os/`, synthetic tests in `tests/`, and related `supabase/` SQL. The current implementation covers event/calendar reconciliation, provider delivery receipts and an experimental display-calendar visibility adapter. Broader household intelligence, agent authorization and low-context document ingestion include planned features, not necessarily executable surfaces.

## Attacker-controlled surfaces and assets

- Provider responses, event metadata, calendar item identifiers, URLs, response errors and API payloads.
- Authorization context and any provider tokens supplied to the reference connectors.
- Requests attempting to cause unauthorized event writes, replay/collision of reconciliation receipts, or cross-household access.
- Untrusted content returned to an AI assistant, which must not be promoted to privileged policy or instructions.
- Confidential calendar details, location, schedules and contact information in a *hypothetical* authorized deployment. No actual such data is permitted in this public repository.

## How to exercise

The scanner image installs the local Python package and runs:

`python -m unittest discover -s tests -v`

The unit tests use fabricated identifiers and mocked provider access. Run offline. Do not contact live calendars, displays, Supabase instances, or external accounts.

## Severity guidance

- **Critical:** a demonstrated unauthenticated path in a supported deployment that exposes or changes a large population's sensitive household data.
- **High:** reproducible cross-user/household access, exposure of provider tokens or private event contents, unauthorized calendar/provider writes, or a privilege escalation in implemented code.
- **Medium:** recoverable synchronization corruption, unwanted duplicates/replays without an authority breach, bounded input-driven resource exhaustion or leakage of low-sensitivity metadata.
- **Low / informational:** documentation gaps, hypothetical unimplemented features, or operator error outside a claimed protection boundary.

State the supported entry point, preconditions, and synthetic impact in each finding. Do not infer that a planned feature is deployed, or publish private findings or any real family, school, calendar or account information.
