# Human review adapter

Source-only implementation for [issue 39](https://github.com/jryski/Household-OS/issues/39).
Nothing in this change installs a hosted migration, creates a live grant, signs
in a person, activates a broker tool, schedules work, or performs an external
action. Human client registration, live login, native PostgreSQL acceptance and
deployment remain later work.

The adapter reads existing `life_ops` boards, work, evidence, dependencies and
activity. Its only new table is authorization configuration,
`life_review.human_grants`. It introduces no household entity model. Existing
worker grants and tools cannot make human decisions.

## Authority and custody

A trusted review host must supply a verified human session and a fixed human
grant binding. The optional sign-in host in `review/host.mjs` supplies that
session from a supported OAuth flow and stays off by default; see
[the review README](../review/README.md#dedicated-human-sign-in-host). A demo
session is never usable as a live credential. Do not send review tokens to a model, worker,
broker delegation or model-callable tool.

Each RPC checks a signed-request subject, upstream OAuth client and current
session through the established identity helper. It checks token expiry,
`auth.sessions` ownership/client/liveness, and the current enabled, unexpired,
unrevoked human grant for the operation and board. Conflicting client claims and
user-metadata-only claims convey no authority. Caller-supplied actor, subject,
client, session, board, approval text or `human=true` is not an authorization
input. The response scope and decision audit derive those values on the server.

The review OAuth client must be newly provisioned for browser-only review and
must never have been in worker custody. A human principal alone is insufficient:
a worker token often has that same principal. SQL compares canonical UUID client
IDs against **all** human and worker grants, including disabled, expired and
revoked rows. Uppercase, compact and braced UUID spellings cannot bypass this
separation. This database check does not certify actual credential custody; that
needs an independent activation review of the host and OAuth client.

Grant configuration remains admin-only, with no configuration RPC. New grants
default to disabled, require an expiry and evidence, and none are seeded. Both
grant guards require READ COMMITTED configuration transactions. Separate
VOLATILE statements take a transaction advisory lock for the canonical client
then inspect the other grant table using a fresh statement snapshot. Native
configuration races have not been qualified in this slice.

Client IDs are immutable and grant rows cannot be deleted or truncated. Revoke a
grant and create another row for the same client when needed. Retaining revoked
rows prevents reclassifying a client while an old worker token might still
exist. Disabling/dropping these guards or rewriting history is a privileged
migration outside this adapter's supported configuration contract.

## Privilege boundary

`life_review_executor` is NOLOGIN, NOINHERIT and NOBYPASSRLS, without role creation
or superuser privileges. No authenticated, anonymous, service or worker role is
its member. It receives only needed read columns/tables, decision update
columns, activity insert/sequence access and the existing base decision RPC.
It has no CREATE privilege on the application schemas, no auth-schema access,
no proposal-write permission and no grant-configuration authority.

The three public facades are SECURITY INVOKER and executable only by
`authenticated`. Their private bounded implementations run as the isolated
executor. The identity-only definer retains the installer's existing auth
privileges and cannot write work, grants or sessions. `life_review` must stay
outside PostgREST's exposed schemas.

The existing `guard_work` and `life_decide_work_v1` definitions change only by
adding the isolated executor to their administrative role allowlists. The
underlying decision RPC is not granted to authenticated or worker roles.
The private decision wrapper is the only callable entry point with decision
authority and checks authorization before item disclosure. It rechecks live
identity, expiry and grant authority after acquiring the item lock. The existing
base function then checks the expected version, rejects terminal work, changes
state, clears the lease and increments the version. A derived human-decision
audit is appended in the same transaction. Failure rolls back both change and
audit.

## UI-facing RPC contract

All responses have `contract: "life-human-review/1"`, `generated_at` and this
scope shape. These are synthetic examples, not real identities or grants:

```json
{
  "human_grant_id": "00000000-0000-4000-8000-000000000301",
  "auth_subject": "00000000-0000-4000-8000-000000000001",
  "upstream_client_id": "00000000-0000-4000-8000-000000000102",
  "session_id": "00000000-0000-4000-8000-000000000202",
  "board_id": "00000000-0000-4000-8000-000000000401",
  "board_key": "life-home",
  "actor_ref": "human:fixture"
}
```

Versions and activity IDs are decimal **strings**. Keep versions as strings
through JSON transport and the comparison step; never convert them to a
JavaScript Number. The RPC's `bigint` parameter accepts that exact decimal string.
Inputs must fit a positive signed PostgreSQL bigint. ISO8601 timestamps may use
a valid offset such as `+00:00`.

| RPC | Inputs | Result |
| --- | --- | --- |
| `life_human_review_queue_v1` | `p_human_grant_id`, optional `p_after_id=null`, `p_limit=10` | `items`, `next_after_id`, `has_more`, `coverage` |
| `life_human_review_item_v1` | `p_human_grant_id`, `p_item_id`, optional `p_limit=10` | `item`, `evidence`, `dependencies`, `activity`, `coverage` |
| `life_human_decide_work_v1` | `p_human_grant_id`, `p_item_id`, `p_expected_version`, `p_state`, `p_decision_ref`, optional `p_outcome_ref=null` | canonical `item` and `authority` |

`p_human_grant_id` is the trusted host binding, never a worker grant. Neither the
host nor the UI should accept an identity or grant override from generated text.

Queue rows have `id`, `title`, `title_truncated`, `state`, `version`, `source_ref`,
`source_ref_omitted`, `due_at`, `not_before`, and `updated_at`. All nonterminal work
on the authorized board is included, ordered by UUID. Count and candidate rows
share a statement snapshot. If more work remains after row/byte limits,
`next_after_id` equals the last **returned** item ID. Otherwise it is null and
`has_more=false`. A supplied cursor must belong to the same board. Pages are not
a transactionally consistent snapshot across separate calls. Coverage includes
`items_omitted`, `external_sources_checked=false` and
`snapshot_consistent_across_pages=false`.

Item fields add `description`, `description_truncated`, `decision_ref`,
`decision_ref_omitted`, `outcome_ref`, `outcome_ref_omitted` and `snoozed_until`.
Evidence rows have `relation`, `source_store`, `source_kind`, `source_key`,
`evidence_ref`, `observed_at` and `references_omitted`. Dependencies have `id`,
`title`, `title_truncated`, `state` and string `version`. Activity has string `id`,
`actor_ref`, `event_kind`, `evidence_ref`, `reference_omitted` and `recorded_at`, in
descending numeric activity order. Arbitrary activity detail is not exposed.
Coverage reports nonnegative `evidence_omitted`, `dependencies_omitted` and
`activity_omitted` plus `external_sources_checked=false`. Detail assembly uses
READ COMMITTED statement reads and can observe concurrent changes; a later
decision always checks the canonical item version again.

Reads never return a lease token. Titles, descriptions and every reference are
untrusted content. Render references as inert text, expose omissions clearly,
and never dereference or execute them on the basis of this response.

## Human actions

The UI must start with a deliberate blank decision input and require an explicit
human action. The decision evidence is an opaque locator/receipt, not a prompt
that can authorize itself. A state change records a human decision; it does not
independently verify a claimed real-world outcome.

| Target state | Meaning here | Required evidence |
| --- | --- | --- |
| `ready` | Allow research to proceed | `p_decision_ref`; `p_outcome_ref` must be null |
| `done` | Record the human's completion claim | Both decision and outcome references |
| `dismissed` | Dismiss the current proposal | Decision reference; outcome must be null |

The base administrative RPC permits `scheduled` but has no scheduling-date
parameter. This adapter deliberately rejects `scheduled`; it does not repurpose
immutable `due_at`/`not_before` proposal facts or invent scheduling semantics.
Existing scheduled items remain readable. No calendar event, payment, outreach
or other external action follows any decision.

Decision/outcome inputs must equal their trimmed form, contain 1..2000
characters, and fit 2048 UTF-8 bytes. Outcome is required only for `done` and must
be null otherwise. `p_expected_version` must be positive. Other target states,
nulls and invalid bounds fail. Terminal `done`/`dismissed` work requires a new
correction proposal, preserving existing base semantics.

Decision responses contain `item.id`, `state`, string `version`, `decision_ref`,
`decision_ref_omitted`, `outcome_ref`, `outcome_ref_omitted` and
`authority: "Human decision recorded; no external action performed."`.

## Bounds and errors

Both read limits are 1..20, default 10. Titles fit 512 UTF-8 bytes; description
fits 4096. Each context list fits 2048 bytes and at most the requested rows.
Individual opaque references fit 512 output bytes or become null with an
explicit omission flag; they are never silently shortened into another locator.
Queue candidates fit 12288 bytes. Every complete response fits 16384 bytes.

| Result | SQL / HTTP behavior |
| --- | --- |
| Wrong subject/client/session/grant/board/operation, expiry or revocation | generic `42501` / HTTP 403 |
| Invalid action/evidence/read bound | `22023` / HTTP 400; SQL type parsing may fail before the wrapper |
| Stale version or terminal-state conflict | public facade `PT409` / HTTP 409 |
| Unexpected database/network/response failure | uncertain; do not infer success or retry automatically |

After a stale or uncertain submission, fetch canonical state and require a fresh
human review. A matching current state alone does not prove that a particular
lost response committed. A stale failure emits no human-decision audit.

## Local checks and deferred acceptance

Run `npm ci --ignore-scripts` and `npm run test:life-human-review`. The test
always creates an in-process PGlite database and has no hosted database mode.
It covers no seeding; role/ACL/ownership; dedicated client separation and UUID
aliases in both directions; retained client history; unsupported configuration
isolation; same-subject worker and forged-label denial; live-session checks;
grant/board/operation scope; version CAS and exact large versions; explicit
outcomes; terminal conflicts; lease cancellation; audit provenance; byte bounds;
inert/omitted references; and byte-limited pagination without skipping rows.

As in the established runtime fixture, PGlite requires precreating three
namespaces under a non-superuser CREATEROLE installer. Only those CREATE SCHEMA
statements are removed from the local migration input. This is not evidence of
unchanged-migration installation on native PostgreSQL. No concurrency result,
cryptographic JWT verification, hosted session, client custody, browser login,
live grant or deployment is qualified by this test. Later acceptance must cover
the exact native installer profile, configuration races, decision/revocation
contention and the complete verified human UI/session path.

To export only synthetic RPC results for a UI schema seam check, set
`LIFE_HUMAN_REVIEW_GOLDEN_OUTPUT` to a local JSON path when running that test.

Migration filename was generated using pinned Supabase CLI 2.121.0:
`20261021020036_life_human_review_adapter.sql`. CLI generation created the file
before automatic review rejected a PostHog telemetry request; no telemetry retry
was performed. Official CLI telemetry opt-outs are
`SUPABASE_TELEMETRY_DISABLED=1` and `DO_NOT_TRACK=1` for future CLI invocations.

Official references checked for this implementation:

- [Supabase changelog](https://supabase.com/changelog) and [RLS guidance](https://supabase.com/docs/guides/database/postgres/row-level-security).
- [Supabase CLI telemetry](https://supabase.com/docs/guides/local-development/cli/getting-started#telemetry).
- [PostgreSQL 17 GRANT](https://www.postgresql.org/docs/17/sql-grant.html).
- [Transaction isolation](https://www.postgresql.org/docs/17/transaction-iso.html), [function volatility](https://www.postgresql.org/docs/17/xfunc-volatility.html), and [advisory locks](https://www.postgresql.org/docs/17/explicit-locking.html#ADVISORY-LOCKS).
