# Household review desk

Source-only reference for [issue #39](https://github.com/jryski/Household-OS/issues/39).
The default UI uses the invented [furnace baseline](../examples/maintenance/furnace-baseline/README.md).
No real account, grant, database, model, calendar or worker is connected by this preview.

## Preview

From the repository root:

```sh
python scripts/serve_review.py
```

Open `http://127.0.0.1:8765`. The loopback-only read-only server exposes an
explicit file allowlist and one synthetic fixture, not the repository directory.
It rejects foreign Host/Origin requests, cross-site browser fetches and all
unimplemented paths/methods. It supplies no-store, no-referrer and restrictive CSP
headers. No preview form can call a live backend. Example decisions affect only
the current tab and are visibly labeled as examples.

## Connected host boundary

`mountReviewDesk(root, client)` is the view. A separately authenticated host can
create its client with `createHumanReviewClient` from `client.mjs`. Host code must
provide all of:

- One pinned hosted Supabase origin and a publishable key. No service key.
- An operator-configured human grant, subject, dedicated review client and board.
- `getVerifiedSession()`, supplied by the host's already authenticated human
  session integration. It returns `verified: true`, `role: 'authenticated'`,
  `subject`, `clientId`, `sessionId`, `expiresAt` (epoch seconds) and an in-memory
  `accessToken`. This assertion is trusted host input, not a browser-module
  proof of token validity or human intent. The SQL boundary independently checks
  signed identity, the live session and current grant for every operation.
- An intent store with `list(prefix)`, `set(key,value)` and `remove(key)`. The
  included `browserIntentStore(localStorage)` adapter retains only minimal
  pending-decision IDs, version, action and time. It stores no credential, note
  text, finding or outcome content. Its keys are scoped to the configured human,
  client, board and grant; its independent attempt keys cannot erase another
  tab's uncertain write. The database's version comparison is the final race
  control. Clearing browser storage is not a safe reconciliation procedure.

The reference does not implement a new OAuth flow, token paste form, automatic
session discovery or client registration. Never pass a human session to a model
or a worker harness. Provision a newly registered browser-only review client that
has never been used for worker custody. A model operating an authorized human
browser cannot be distinguished from the person by these database grants alone.
Use a dedicated human interaction boundary and explicitly authorize deployment.

The host serves its own authenticated entry page and a CSP allowing only its
exact pinned API origin. The supplied preview server remains deliberately
disconnected; do not weaken its CSP to turn a demo into a production deployment.
No URL parameter, source record or model message selects the host configuration.

## Decision behavior

The person chooses an action and supplies a decision record. Completion also
requires an outcome record. Nothing is preselected or filled from a source.
The submitted decimal version is the version that was rendered, without JS
Number conversion. Only ready, done and dismissed are supported; scheduling
needs a later explicit date contract.

Source references are inert selectable text. The view never fetches those
sources, renders record text as HTML, or turns a recommendation into an accepted
outcome. Coverage and omissions remain visible.

The client sends each decision once and journals intent before dispatch. A lost,
timed-out, malformed or ambiguous successful reply leaves a pending record and
blocks another attempt, including after reload. Reading the latest task does not
prove which attempt caused its state. An operator must reconcile that pending
decision; the UI provides no automatic retry or clear-and-retry button. Known
denial, validation rejection and stale-version conflicts are reported separately.
Explicit reload after a stale conflict starts a new human review, not a replay.

## Development checks

```sh
node --test scripts/test_review_client.mjs
```

These are offline contract/dispatch/uncertainty checks. They do not establish real
OAuth, dedicated-client setup, live database decisions or human acceptance.
The new human-review migration remains unapplied until a later qualified pilot.
The browser executable is unavailable in this development environment, so visual,
keyboard and responsive-layout acceptance also remain for that later session.
