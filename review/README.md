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

The view and client do not implement OAuth, a token paste form, automatic
session discovery or client registration; the optional host below uses the
supported Supabase OAuth 2.1 flow. Never pass a human session to a model
or a worker harness. Provision a newly registered browser-only review client that
has never been used for worker custody. A model operating an authorized human
browser cannot be distinguished from the person by these database grants alone.
Use a dedicated human interaction boundary and explicitly authorize deployment.

The host serves its own authenticated entry page and a CSP allowing only its
exact pinned API origin. The supplied preview server remains deliberately
disconnected; do not weaken its CSP to turn a demo into a production deployment.
No URL parameter, source record or model message selects the host configuration.

## Dedicated human sign-in host

`host.html` with `host-entry.mjs` and `host.mjs` is the optional host for the
connected desk. Its configuration is `host-config.mjs`, which ships as
`{mode: 'example'}`. With that default it mounts the same invented example as
the preview and makes no network request. The preview server does not serve the
host files, and its CSP still blocks any backend.

### Supported flow

The host is a **public OAuth client of Supabase Auth's OAuth 2.1 server**:
authorization code with PKCE (S256), `token_endpoint_auth_method: none`, scope
`openid`, plus `state` and `nonce`. It uses only the documented
`/auth/v1/oauth/authorize`, `/auth/v1/oauth/token` and
`/auth/v1/.well-known/jwks.json` endpoints of the pinned project. It adds no
OAuth server, token paste form, client secret or app framework.

### Required claims and how they are established

The SQL boundary (`life_runtime.request_identity` and `life_review.authorize`)
requires every one of these. The host checks them only after verifying the
token signature with WebCrypto against the project's JWKS (ES256 or RS256; the
`none`, HMAC, embedded-key and unknown-key cases are rejected):

| Requirement | Access token | Also checked |
| --- | --- | --- |
| Signed by the pinned project | JWS signature, `iss` = `<origin>/auth/v1` | ID token signature and `iss` |
| Live, unexpired | `exp` (and `nbf`/`iat` skew) | SQL: `auth.sessions` row, `not_after` |
| Ordinary user role | `role` = `authenticated`, `aud` = `authenticated` | |
| Dedicated review client | `client_id` = pinned client; no conflicting `app_metadata.client_id` | ID token `aud` = pinned client; SQL: `auth.sessions.oauth_client_id` |
| Configured person | `sub` = binding `auth_subject` | ID token `sub` matches; nonce matches this sign-in |
| Session identity | `session_id` is a UUID | SQL: session belongs to the subject and client |
| Grant and board | not in the token | SQL: current enabled grant for subject, client, board and operation |

Only after all of these pass does the host give the existing
`createHumanReviewClient` a session with `verified: true`. The three-RPC client,
its rendered-version checks and its uncertain-write journal are unchanged.

### States

- **Example**: default configuration.
- **Disconnected**: connected configuration present but `enabled: false`,
  invalid, served from a different origin than the pinned redirect, or the
  token endpoint unavailable.
- **Signed out**: ready to sign in, after sign-out, or after token expiry.
- **Denied**: sign-in refused, verification failed, stale or replayed callback,
  or a verified account that is not the configured reviewer.
- **Connected**: desk mounted for exactly one verified session.

Sign-out, expiry or a new sign-in destroys the mounted desk and its client. The
old client then refuses to dispatch, and the next session starts a fresh review.
The host never touches the pending-decision journal, so an unresolved decision
still blocks a repeat attempt after signing in again.

### Redirect, origin and credential custody

- The redirect URI is one exact pinned HTTPS URL on the host's own origin, with
  no query or fragment. The host refuses to run anywhere else.
- Only the documented callback parameters are accepted (`code` and `state`, or
  `error`, `error_description` and `state`). The code is removed from the address
  bar before the exchange. State, PKCE verifier and nonce live in
  `sessionStorage` only until the callback and are single-use, valid for 10 minutes.
- Access and ID tokens are held in memory only. The refresh token is discarded,
  so a new sign-in is required when the access token expires. Nothing is logged.
- Requests use `credentials: 'omit'`, `redirect: 'error'`, `no-store` and
  `no-referrer`. No configuration value is read from the URL.
- Serve `host.html` with a CSP whose `connect-src` is `'self'` plus the exact
  pinned project origin, with `frame-ancestors 'none'` and `form-action 'none'`.

### Inputs still needed before activation

The source cannot supply these. Connected mode stays off until a separately
approved activation provides all of them:

1. Supabase OAuth 2.1 server enabled on the project, with an **authorization
   (consent) page** at the configured authorization path. That page signs the
   person in and calls the approve/deny methods; it is not part of this host.
2. **Asymmetric JWT signing keys** (ES256 or RS256). ID tokens and in-browser
   verification are unavailable with the legacy HS256 secret.
3. A newly registered **public** OAuth client for review only, never used for
   worker custody, whose only redirect URI is the pinned host callback.
4. No custom access token hook that removes or rewrites `client_id`,
   `session_id`, `role` or `aud`.
5. The human-review migration applied and an enabled `life_review.human_grants`
   row for the subject, client and board.
6. A deployed HTTPS host for these files with the CSP above, and the filled-in
   `host-config.mjs` values.

### Run guide

Offline checks only:

```sh
npm ci --ignore-scripts
npm run test:life-review-host
npm run test:life-review-client
```

The host tests use a synthetic auth server with keys generated for each run.
They cover the default example mode, disabled and invalid configuration, the
PKCE request, the verified callback, invalid, expired and wrong-client sessions,
state and replay handling, outages, sign-out and session change with the
journal preserved, and expiry. They do not exercise a real project, a browser,
a consent page or a real account.

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
