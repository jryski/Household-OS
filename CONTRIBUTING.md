# Contributing to Household OS

Household OS is a public reference repository. Contributions must stay inside
the public-repository rule: structure, generic policy, synthetic fixtures, and
sanitized lessons. Real household data does not belong here.

## Read these first

- [README](README.md) — purpose, architecture, and the
  [public-repository rule](README.md#public-repository-rule).
- [PROGRAM-ROLE.md](PROGRAM-ROLE.md) — what this repository owns, what it does
  not own, and the privacy boundary between HOUSE and VAULT.
- [DCO.md](DCO.md) — Developer Certificate of Origin. There is no separate
  Contributor License Agreement.
- [LICENSE](LICENSE) and [NOTICE](NOTICE) — Apache License 2.0 and copyright
  notice. [docs/THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md) records
  inbound material from other projects.

## Issue first

Open an issue, or link an existing one, before opening a pull request. Use the
docs/planning or feature templates when they fit. Describe the change in terms
of public structure and synthetic examples.

Say which program gate the work serves:

| Gate | Meaning for this repository |
| --- | --- |
| **A** | Safe contributor launch. Public docs, templates, and hygiene that do not leak private context or expand live authority. |
| **B** | Synthetic read-only reference. Contracts and fixtures that demonstrate discovery or retrieval with fabricated data only. No real-user data plane. |
| **C** | Separately authorized real-user or production-adjacent deploy. Gate C is not implied by finishing Gate A or Gate B. It needs its own explicit authorization. Do not start it from a docs issue or from Gate A/B completion. |

Program context for these gates lives on
[WireSpeedComputing/sovereign-ai-os#52](https://github.com/WireSpeedComputing/sovereign-ai-os/issues/52)
(coordination note MC1297). That map's dependency edges stay proposed until an
owner validates them. Do not treat this file as creating those edges.

## Docs-only merges (D3)

A docs-only pull request may be merged only when both of these are true:

1. CI on the pull request is green.
2. An independent reviewer who is not the author has approved it.

The author does not merge their own pull request. A bot run, an automated
comment, or a non-docs change is not a merge claim under this policy. Do not
state that a pull request is merged, or that a non-docs change merged, unless
those two conditions are met and the merge has actually landed.

This policy covers documentation and templates. It does not authorize schema
changes, migrations, application code, credentials, deploys, or live data-plane
work.

## Privacy boundary

Never commit, paste into an issue, or attach:

- real HOUSE or VAULT records;
- names or identities of real household members;
- addresses, schools, employers, birthdays, schedules, travel, health, finance,
  or family records;
- credentials, tokens, keys, or secrets;
- production database identifiers, URLs, account IDs, calendar IDs, or other
  provider object IDs;
- private infrastructure topology that is not required to explain the public
  architecture;
- screenshots, exports, logs, receipts, prompts, or traces that contain real
  household content.

Use synthetic identifiers only. Established examples in this repository include
`person-1`, `agent-1`, `project-demo`, and `calendar-demo`.

## Domain design ownership

Household domain design is owned outside this public-docs steward lane, by the
household domain design owner (claude-warden). Do not invent ontology here
casually. Entity models, family profiles, and related domain semantics are that
owner's design. Contributors may document structure that is already public and
may file synthetic-safe issues. New domain concepts need that owner's design
before they become repository structure.

## Issues you must not claim

If an issue carries `quarantine:privacy` or `bot:do-not-execute`, leave it
alone. Do not claim it, schedule it, or execute it. Those labels are not part
of this repository's default set. This note does not create them. If an
authorized owner applies either label later, the exclusion still holds until
that owner lifts it and reclassifies the issue.

## Pull requests

1. Branch from current `main`.
2. Keep the change scoped to the linked issue.
3. Sign every commit with the Developer Certificate of Origin:

   ```bash
   git commit -s
   ```

   That appends `Signed-off-by: Your Name <you@example.com>`. Use your real
   name. A provider no-reply address is acceptable. See [DCO.md](DCO.md).
4. Fill in the pull request checklist, including whether the change is docs or
   code, the privacy boundary, and the DCO sign-off.
5. Wait for green CI and an independent review (author ≠ reviewer) before any
   docs-only merge. Leave the pull request unmerged until then.

Do not add `CODEOWNERS`, live schema, migrations, secrets, or deploy workflows
as part of a docs-only contribution.
