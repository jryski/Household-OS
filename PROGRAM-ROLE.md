# Program role: Household OS

> **Program:** Sovereign AI OS  
> **Role class:** household-domain deployment and application layer  
> **Program context:** [`Sovereign AI OS`](https://github.com/jryski/sovereign-memory-core/blob/main/docs/ecosystem/SOVEREIGN_AI_OS.md)

## Mission

Household OS models a household's shared reality and coordinates family work through provider-neutral, agent-assisted applications. It turns governed memory, observations, plans, events, integrations, and action receipts into useful household behavior.

It is the first organizational deployment of the broader Sovereign AI OS architecture. Business deployments reuse the kernel ideas but require their own ontology, policies, and stores.

## This repository owns

- public household-domain schemas, interfaces, and synthetic fixtures;
- people, household roles, locations, assets, services, projects, events, school, maintenance, and other shared-domain concepts;
- household planning and virtual-kanban behavior;
- connector observation, reconciliation, and external-reference contracts;
- household authority, approval, privacy, and child-access profiles;
- bounded context and troubleshooting examples;
- sanitized, reproducible deployment lessons.

## This repository does not own

- Sovereign Memory Protocol semantics;
- the generic Core custody implementation;
- principal-bound MCP identity implementation;
- business products, suppliers, customers, employees, or company policy;
- the agent runtime or model qualification system;
- any real household data, topology, credentials, schedules, or identifiers.

## Upstream dependencies

- SMP and a conforming or compatible durable memory runtime;
- Supabase User MCP or another principal-bound data plane before multi-principal access is trusted;
- versioned context, capability, planning, action, receipt, and connector contracts.

## Downstream consumers

- private HOUSE deployments;
- family-facing applications and review surfaces;
- household agents and integration adapters;
- synthetic examples that test the shared organizational kernel.

## Planning and work-plane relationship

Planning is first-class Household OS behavior. The household source of truth should coordinate family projects, school, activities, events, chores, routines, maintenance, purchases, and errands using durable shared work objects rather than chat-bound promises.

Google Calendar, Skylight, school systems, mail, and other providers are adapters or authorities for their own external objects. They do not silently replace the household board's canonical work identity, dependency, review, and activity history.

Low-friction calendar ingestion is part of that planning surface: setup can optionally configure category delivery targets, dated artifacts can become canonical events with minimal context, and those events can spawn governed preparation work. Provider capability gaps degrade delivery, not canonical intake or Kanban coordination.

See [`docs/PLANNING_WORK_PLANE.md`](docs/PLANNING_WORK_PLANE.md), [`docs/IMAGE_CALENDAR_INTAKE.md`](docs/IMAGE_CALENDAR_INTAKE.md), and [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Privacy boundary

Shared household coordination belongs in HOUSE. Principal-private notes, interpretation, sensitive personal records, and restricted annotations belong in that principal's VAULT or another appropriate trust domain. Private content is not modeled as a hidden afterthought inside an otherwise shared row.

Child or guest access is not considered enforced until principal-bound identity and database policy are proven below the model.

## Public-repository rule

Only structure, generic policy, synthetic fixtures, and sanitized lessons belong here. Never commit real names, addresses, schools, schedules, birthdays, finances, health records, household topology, credentials, provider IDs, screenshots, exports, or copied HOUSE/VAULT content.

## Agent boundary

Do not broaden SMP or Core to solve household convenience. Do not copy Business OS tables into this repository merely because both deployments need planning. Reuse shared contracts, then implement household-specific semantics here.
