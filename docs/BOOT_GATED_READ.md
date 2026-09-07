# Boot-gated HOUSE day brief

Operator-only command for reading a scoped HOUSE day brief after an explicit session boot. This path queries HOUSE RPCs only. It does not fall back to VAULT, memories, images, storage buckets, Google Calendar, or direct SQL.

## Command

```bash
household-day-brief --date 2030-09-10 --timezone UTC --viewer shared --live-read
```

| Flag | Required | Description |
|------|----------|-------------|
| `--date` | yes | ISO calendar date (`YYYY-MM-DD`) |
| `--timezone` | yes | IANA timezone for the requested date |
| `--viewer` | no | Viewer filter (default: `shared`) |
| `--live-read` | yes for I/O | Must be present for any network access |

`--help` and validation-only failures never read credentials or contact services.

## Configuration

Server-side environment only (see `.env.example`):

- `HOUSE_SUPABASE_URL`: HTTPS origin only (no path, query, userinfo, or fragment)
- `HOUSE_SUPABASE_SERVICE_ROLE_KEY`: privileged service role key

The service role key is shared operator credentials. It is not user-bound authorization. The `--viewer` flag filters scoped results; it does not authenticate an end user.

**Do not expose this command to untrusted users, browser clients, or public endpoints.**

## Flow

1. Validate date, timezone, and (when `--live-read` is set) configuration.
2. Call `session_boot(p_viewer)` on the configured HOUSE endpoint.
3. Validate boot: matching viewer, advertised `day_brief` capability (exact function name), `instruction_integrity` of `match`, `health.capability_manifest_stale` exactly `0`, and fresh `booted_at` (max age 5 minutes).
4. Call `day_brief(p_viewer, p_date, p_timezone)`.
5. Validate brief shape and exact viewer/date match.
6. Print scoped JSON to stdout.

Each invocation performs one fresh boot and one brief query on the same transport. Boot failures are never treated as an empty brief.

## Success output

Stdout is JSON with:

- `coverage`: always `queried_house_for_requested_date`
- `data`: scoped brief fields (`viewer`, `date`, `weekday`, `school`, `lunch`, `events`, `channel_open`, `menu_coverage`)

Empty `lunch` or `events` arrays mean no scoped rows for the request, not that the feature is unimplemented or globally absent.

**Warning:** success output may contain household-scoped data. Do not publish stdout to logs, tickets, or public channels.

Boot topics, inbox, and debug payloads are never included in success output.

## Errors

Human-visible failures print a single stable code to stderr (no upstream text, URLs, tokens, or tracebacks). Examples:

- `live_read_required`
- `invalid_date`, `invalid_timezone`, `timezone_unavailable`, `invalid_viewer`
- `config_missing_url`, `config_missing_key`, `config_invalid_url`, `config_invalid_transport`, `config_transport_mismatch`
- `boot_viewer_mismatch`, `boot_capability_missing`, `boot_integrity_mismatch`, `boot_drift_detected`, `boot_stale`, `boot_future`, `boot_malformed`
- `brief_viewer_mismatch`, `brief_date_mismatch`, `brief_malformed`
- `transport_error`, `redirect_refused`, `response_too_large`, `rpc_not_allowed`
- `command_failed` (unexpected internal failure; stdout reports `{"coverage":"unavailable"}`)

On Windows, if `zoneinfo` cannot resolve a timezone (missing `tzdata`), the command reports `timezone_unavailable` honestly. It does not install packages.

## Security boundaries

- HTTPS origin only; redirects (including same-origin path or query changes) are refused before credentials are forwarded.
- RPC transport allows only `session_boot` and `day_brief`.
- Bounded timeout and response size.
- No fallback data sources.

## Related commands

`household-calendar-sync` remains the calendar reconciliation entry point. This read command is separate and does not replace it.

## Verification and remaining integration

On September 7, 2026, all 68 offline unit tests passed on Python 3.13, including the existing calendar/display tests and boot-gated read regressions. Cursor authored the batch; Locutus reviewed it and corrected URL parsing and test patches after Cursor stopped. No production endpoint, household payload, browser or live provider was used in these tests.

This command makes boot mandatory only for calls through this command. It does not force an existing mobile or voice assistant to use it. Wiring an authorized client to this path, testing a real operator invocation and establishing principal-bound authorization remain separate work. The endpoint is explicitly operator-configured, not inferred from a calendar name; a configuration label alone does not attest server identity.

There are no database migrations or production changes in this batch. Success output is sensitive; test with synthetic data before enabling routine use. Missing timezone data is a setup blocker, not permission to install packages automatically.
