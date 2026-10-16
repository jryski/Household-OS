# Life assistance work plane

Implements the existing planning objects from `PLANNING_WORK_PLANE.md` without
introducing a person, asset, medical, or financial ontology. Tracked in issue #35.

The portable migrations add boards, proposed work, source links, dependencies,
append-only activity, permitted source signals, configurable routines, and bounded
agent check-ins. References point back to existing records in their original trust
domains. Private records must not be copied into shared descriptions or signals.

## Initial implementation boundary

All tables are in the restricted `life_ops` schema with RLS enabled. The eight
`public.life_*_v1` functions use security-invoker permissions. Anonymous and
authenticated database roles have no access. Service-role access is for trusted
server infrastructure, not an agent credential or a proof of human identity.

Actor strings record attribution only. They do not authenticate a principal.
Connecting individual agents or household users requires an independently tested
principal-bound broker adapter. This change does not claim the HOS-3 milestone.

Only the administrative decision path can accept work or record an accepted
outcome. The service role can submit proposals and research results, but cannot
grant itself acceptance, alter board policy, or call the decision RPC. No function
contacts a person, spends money, changes a calendar, or executes medical advice.

## Capabilities

| Function | Result |
| --- | --- |
| `life_propose_work_v1` | Evidence-linked proposal; stable-key retries return one item and conflicting payloads fail. |
| `life_record_signal_v1` | Append-only source reference and bounded matching keys; repeat ingestion is idempotent. |
| `life_check_in_v1` | A bounded open-work selection and incremental signal page, with explicit coverage and continuation. |
| `life_claim_work_v1` | Atomic, expiring research lease; checks board policy, dependencies, and timing. |
| `life_submit_work_v1` | A finding or blocker from the live lease; moves work to review or blocked. |
| `life_decide_work_v1` | Administrative, version-checked acceptance or dismissal; completion requires outcome evidence. |
| `life_materialize_routines_v1` | Due interval or annual/seasonal routines become proposals, coalescing missed occurrences and already-open work. |
| `life_match_recall_signals_v1` | Exact supplied key overlaps produce possible-match proposals with both source references. |

## What remains external

An ingestion adapter supplies source signals. An authorized evaluator or scheduler
invokes matching and routines. No scheduled jobs are installed by this migration.
Agents reason over permitted evidence and propose useful links; this is not an
automatic universal relevance detector. A receipt match is not confirmed exposure:
product identity, lot, purchase dates, and current possession still need checking.
Revised external information must arrive under a new revision-specific signal key.

Calendar/list delivery, contractor research connectors, authenticated approval UI,
and individual agent integration remain adapter work. Existing calendar and memory
surfaces are unchanged. Identical schema in two stores does not federate them.

## Deployment

Apply the migration separately to each authorized trust domain. Create a board
through an administrative connection; real board records and deployment receipts
belong in the private deployment repository. There is no portable seed household.
Routines default to disabled and need an approved schedule and evidence reference.
Store intervals are elapsed days; annual dates use the configured timezone and
clamp invalid month-end dates (including leap day) to that month's last day.

Never register a broad service-role key as an agent's credential. Connecting an
agent requires operation and board allowlists and verified identity in the broker.

## Verification

Run `npm ci --ignore-scripts` followed by `npm run test:life-db`. The test harness
uses pinned PGlite PostgreSQL 17 and synthetic data in an ephemeral local database.
It exercises permission denial, proposal idempotency, decision separation, leases,
dependencies, append-only history, bounded cursors, seasonal dates, routine
coalescing, and conservative recall matches. It does not simulate independent
PostgreSQL sessions; real concurrent-session races remain a separate deployment
qualification check. Run the existing Python suite with
`PYTHONPATH=src python -m unittest discover -s tests -v`.
