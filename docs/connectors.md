# Provider Connector and Reconciliation Model

## Principle

External applications are operational providers, not automatic sources of canonical truth.

Household OS should integrate with strong existing applications instead of recreating them. The system owns the canonical relationship between household objects and provider objects.

## Canonical object and provider link

A canonical object may have zero or more provider links.

Example:

```text
canonical event
  -> provider link A -> external calendar event
  -> provider link B -> household display event
  -> provider link C -> imported school event
```

Provider identifiers and provider-specific metadata belong in adapter/link records, not in the canonical domain object.

## Connector responsibilities

A connector may:

- authenticate to an external provider using deployment-managed credentials;
- observe external objects and changes;
- map provider objects to canonical candidates;
- maintain sync cursors and provider links;
- propose canonical changes;
- execute authorized outbound changes;
- record results, failures, retries, and reconciliation state.

A connector must not silently decide that provider state overrides canonical authority.

## Observation model

An inbound provider change should create or update an observation containing at least:

- provider type;
- provider-side object reference;
- observed timestamp;
- provider update/version token when available;
- normalized candidate fields;
- mapping confidence/state;
- canonical object link when resolved;
- source classification.

Raw provider payload retention is deployment policy and must respect privacy, licensing, and minimization requirements.

## Reconciliation states

A generic provider link can be modeled with states such as:

- `unlinked`
- `linked`
- `in_sync`
- `provider_ahead`
- `canonical_ahead`
- `conflict`
- `pending_write`
- `write_failed`
- `ignored`

The exact implementation may vary. The important property is that divergence is visible rather than silently overwritten.

## Calendar/event adapter

A calendar adapter should support:

### Read

- list changes since a cursor;
- fetch one external event;
- observe create/update/delete state;
- capture recurrence and exception semantics without flattening them prematurely.

### Propose

- create canonical event candidate;
- link an existing canonical event;
- propose time/location/participant changes;
- flag collisions or ambiguous matches.

### Write

Only with appropriate authority:

- create external event;
- update external event;
- cancel/delete external event;
- add/remove participants where the provider permits it.

Every outbound operation should be idempotent or replay-safe where practical and produce an execution receipt.

## Multiple calendars and displays

Two providers may represent the same household event. Household OS should not duplicate the canonical event merely because two external IDs exist.

Matching may consider normalized time, title, participants, source, recurrence, and explicit links, but uncertain matches remain proposed rather than silently merged.

## Planning context

Agents may use approved canonical events and provider observations to reason about:

- availability;
- conflicts;
- travel windows;
- school/work constraints;
- preparation tasks;
- event-dependent work.

Planning access does not imply write authority.

## Failure behavior

Connectors should expose:

- stale cursor/state;
- authentication failure;
- provider outage;
- rate limiting;
- partial success;
- ambiguous mapping;
- rejected write;
- unresolved conflict.

A stale or unavailable provider must not be represented as current merely because the last sync succeeded.

## Public repository rule

Examples in this repository must use fabricated provider names/identifiers or generic placeholders unless documenting a public API contract. Never commit real account IDs, calendar IDs, event IDs, webhook secrets, access tokens, household schedules, or private provider payloads.
