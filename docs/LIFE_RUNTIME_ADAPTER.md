# Authenticated life-work adapter

This optional layer builds on [the existing work plane](LIFE_ASSISTANCE_WORK_PLANE.md).
It lets a verified delegated worker read bounded context, record a check-in,
claim research, and submit a finding for review. It does not accept outcomes,
alter policy, configure routines, ingest sources, or execute external actions.

## Authority and defaults

The migration creates **no grant rows**. New administrative grant rows default
to disabled and require an explicit expiry and evidence reference. Applying
the source does not enroll an agent or change a running broker.

A grant binds an authenticated upstream subject and client to one board, a
configured actor reference, and a subset of `context`, `check_in`, `claim`, and
`submit`. It narrows an existing human delegation; it does not create a new
identity authority or prove that a person approved an individual action.
Runtime callers cannot create, enable, change, or revoke grants.

Every operation derives the subject from `auth.uid()` and the client from
server-controlled JWT `client_id`, falling back to `app_metadata.client_id`.
Conflicting top-level and nested values, missing values, invalid types, empty
values, whitespace and overlong client IDs are denied. `user_metadata` is
never authority. A private identity-only helper also checks numeric JWT expiry,
session UUID, and a current `auth.sessions` row with matching subject and OAuth
client and an unexpired `not_after` when set. A deleted session rejects even a
still-unexpired token. The Data API and broker remain responsible for token
signature, issuer and audience validation. SQL tests use auth shims and do not
establish cryptographic verification.

The broker must inject the configured grant UUID from trusted request policy,
alongside the current authenticated user token. The model supplies neither
grant, actor, client, subject, board, role nor function name. A grant UUID is a
locator, not a bearer credential: SQL also checks the authenticated request,
current grant, operation, and board on every call. Context, claim, and submit
cross-check the item's actual board. Revocation after check-in blocks claim;
revocation after claim blocks submission. A grant row lock serializes an
operation with administrative changes to that grant.

Work implementation functions run as a non-login, non-administrative role
without `BYPASSRLS`. The role receives only the object privileges and additive
RLS policies needed for these four operations. Public facades use invoker
security. No authenticated caller gets direct table access or executor-role
membership. Keep `life_runtime` outside the exposed API schemas. Existing
administrative decisions, base APIs and caller policies remain unchanged.

The identity-only helper remains owned by the installer, using its existing auth
privileges, and cannot mutate work, grants, policy or sessions. Only the executor
can call it. This avoids regranting hosted auth-schema privileges the installer
does not hold with grant option. PostgreSQL 16+ ownership transfer uses temporary
executor SET and schema CREATE privileges; both are removed afterward. An
automatic creator ADMIN-only membership may remain without SET or INHERIT.

## Fixed RPC contract

| Public RPC | Fixed broker input | Tool input | Annotation |
| --- | --- | --- | --- |
| `life_runtime_context_v1` | `p_grant_id` | `p_item_id`, optional `p_limit` | Read-only |
| `life_runtime_check_in_v1` | `p_grant_id` | `p_evidence_ref`, optional `p_after_signal`, `p_limit` | Writes a check-in |
| `life_runtime_claim_work_v1` | `p_grant_id` | `p_item_id`, optional `p_lease_seconds` | Claims research |
| `life_runtime_submit_work_v1` | `p_grant_id` | `p_item_id`, `p_lease_token`, `p_finding_ref`, optional `p_blocked` | Submits for review |

Each result carries `contract` and a `scope` object with `grant_id`,
`auth_subject`, `upstream_client_id`, and `board_id`. The broker must verify
these fields against its verified request and configured binding before
returning data. Removing this internal scope from the model-facing output is
permitted after verification.

Context and check-in include the assembly time as `generated_at`. Context returns
item description and version, evidence locators, dependency
states, recent activity, and coverage. It never returns a lease token or
dereferences another trust domain. Claim returns the new lease token only to
the claiming request. Submission binds both the token and the exact grant's
recorded claim version, so reusing an actor label in a second grant does not
transfer an existing lease.

The section limit is 1–20. Context and check-in results have a 16 KiB serialized
UTF-8 ceiling. Prose may be shortened with a flag. Oversized opaque references
are omitted with flags, never shortened into another locator. Sections have
separate byte bounds and explicit omitted counts. Signal matching keys stay
outside model context. Only returned signal rows advance the caller's cursor;
the underlying check-in records the original bounded database selection.
The broker still enforces its complete response-frame budget.

## Failures and recovery

Unknown or unauthorized grant/item, wrong subject/client/board/operation,
disabled board, and expired or revoked authority return a generic `42501`
denial. Invalid bounds return `22023`. Unclaimable or invalid/consumed leases
return `PT409` from the public facades, which PostgREST maps to HTTP 409. Internal
base APIs retain `55000`. Only that known rolled-back lease conflict is remapped;
unexpected server errors remain failures with uncertain-result handling. Bounds
`22023` map to HTTP 400; response-budget failures retain `54000`. Neither a finding
nor a successful submission is an accepted household outcome.

Claim and submit retain the base API's non-replayable lease semantics. A lost
response after commit is an **uncertain result**, not a retry instruction.
Persist a confirmed lease token in the worker checkpoint. If a claim response
is lost, stop and reconcile or wait for expiry before reclaiming. If submission
is uncertain, inspect canonical state; do not submit again or infer acceptance.
This change does not implement a new replay/reconciliation endpoint.

## Validation and deployment boundary

Run `npm ci --ignore-scripts`, `npm run test:life-db`, and
`npm run test:life-runtime`. Synthetic tests exercise scope, wrong-board reads
and writes, malformed client claims, revocation, operation denial, grant-bound
lease submission, direct-access denial, bounded context and review-only results.
The existing Python suite remains applicable to the calendar code.

PGlite is single-session PostgreSQL 17. The installer test runs the SQL under a
non-superuser CREATEROLE role without auth-schema grant options. PGlite cannot
change database ACLs (`XX000: tuple concurrently deleted`), so that fixture
precreates only the two owned namespaces and omits their exact CREATE SCHEMA
statements; every other migration statement executes unchanged. Full PostgreSQL
namespace creation is still an acceptance requirement.

The same runner supports native PostgreSQL 17. Set `LIFE_RUNTIME_DATABASE_URL`
to a fresh, isolated database named `life_acceptance` or `life_runtime_fixture`
on loopback, and `LIFE_RUNTIME_POSTGRES_ACK=synthetic-disposable`. Authentication
credentials belong in the environment, not source or logs. This mode executes
the exact migration files unchanged with a real non-superuser CREATEROLE
installer lacking auth-schema grant options. It also opens two independent
connections, races claims, observes actual database lock blockers during
revocation, and proves both operation-first and revocation-first ordering.
It does not reset an existing database. Use a fresh disposable instance per run.

The GitHub Actions `PostgreSQL 17 runtime and contention` job runs that native
mode using the same immutable official PostgreSQL 17 image digest retained in
its service definition. The PGlite job remains the fast path. Synthetic goldens
can be exported with `LIFE_RUNTIME_FIXTURE_OUTPUT` for cross-component schema
checks; they contain only fabricated fixture data.

Neither backend verifies cryptographic JWTs, a broker release, live grants,
independent review or deployment. Before activation, inspect the target auth
helpers and API schema configuration, review a specific grant and broker
binding, and retain exact-source and rollback receipts privately.

For safe disable, an administrator disables or revokes the new grant. Existing
calendar and memory paths remain available. Do not remove base work-plane
history or broaden a runtime grant to bypass a failed acceptance check.

References checked for this implementation:
[Supabase function security](https://supabase.com/docs/guides/database/functions),
[RLS](https://supabase.com/docs/guides/database/postgres/row-level-security), and
[PostgreSQL function security](https://www.postgresql.org/docs/current/sql-createfunction.html).
Native harness references:
[node-postgres Client](https://node-postgres.com/apis/client),
[PostgreSQL 17 GRANT](https://www.postgresql.org/docs/17/sql-grant.html),
[locking](https://www.postgresql.org/docs/17/explicit-locking.html), and
[PostgREST error mapping](https://docs.postgrest.org/en/stable/references/errors.html).
