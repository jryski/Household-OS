# Household OS Roadmap

_Status: public reference-architecture roadmap; no deployment authority_

## Phase 0 — Boundary and publication discipline

- Keep public/private deployment surfaces separate.
- Define architecture, contribution, sanitization, and synthetic-fixture rules.
- Consume protocol/runtime capabilities without redefining upstream semantics.

## Phase 1 — Verified user identity and visibility

- Integrate a non-service authenticated user path.
- Map store-local subjects to stable deployment principals.
- Make display/access derive from tested policy rather than hardcoded UI assumptions.
- Keep provenance labels separate from authorization identity.

**Gate:** no claim of user-scoped authorization until the real request path reaches policy/RLS as that user.

## Phase 2 — Core household operations

- projects and work items;
- lists and shared household planning;
- event/calendar canonical model;
- provider observation/reconciliation;
- bounded agent proposals and review surfaces.

## Phase 3 — Governed agent capabilities

- consume bounded MCP tools rather than generic database/admin access;
- require explicit capability boundaries for reads/writes;
- preserve proposal/approval/receipt semantics for authority-bearing changes;
- test cross-principal and hostile-content cases with synthetic fixtures.

## Phase 4 — Governed artifact inspection

Once the user-context capability and Storage security gates are accepted:

- inspect durable artifacts by opaque ID;
- bounded range/section reads;
- deterministic structure/index derivations;
- source-bound provenance for summaries/derived artifacts;
- no generic bucket/path access or signed-URL shortcut.

## Phase 5 — Legacy/in-situ source onboarding

If the proposed SMP Agent Access Integrity Boundary is eventually accepted:

- declare protected native surfaces before agent enablement;
- preserve T0 commitment/evidence and claim limits;
- bind first agent access to accepted enrollment evidence;
- classify post-T0 changes under explicit observation/attribution assurance.

Household OS consumes this profile; it does not define it.

## Phase 6 — Operational maturity

- recovery and restore evidence;
- connector drift and reconciliation drills;
- provider replacement;
- failure/degraded-mode behavior;
- independent security review of the deployed trust boundaries.

## Standing rules

- Public repository stays synthetic-only.
- No private deployment artifact becomes public by visibility flip.
- Protocol meaning flows down; deployment policy does not flow up.
- Privileged backend success is not proof of user authorization.
- A green test states its evaluated surface and claim limits.
