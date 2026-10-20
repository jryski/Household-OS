# LEAK-01 activation receipt, 2026-10-20

The repository leak guard is operational and required for the public default branch. This receipt distinguishes workflow activation from whole-history or complete privacy certification.

## Reviewed source

Repair [PR #32](https://github.com/jryski/Household-OS/pull/32), head `e0aa9a33dadf00019706d24916aece6b6557676d`, was independently reviewed and merged as `cbc71b166eb654ecd1b80208211bd68a0cd8b9cf`.

The repair moves `cancelled()` from an invalid step environment expression into the step condition. Cancellation retains a blocking pending result. Trusted-base scanner execution, private-pattern isolation, immutable target revisions, redacted reports, and fail-closed behavior remain enforced.

Pinned actionlint 1.7.12 and Gitleaks 8.30.1 qualification: 81 tests passed with zero skips. Synthetic clean, planted-finding, and exact-head controls passed.

## Protected configuration and hosted evidence

A bounded private-identifier policy v1 was provisioned through protected secret management. Canonical encoding, regex validity, intended positive controls, benign controls, and private local custody were checked. No policy expressions or matched values are recorded here. This is not a complete PII classifier.

- [Trusted push scan](https://github.com/jryski/Household-OS/actions/runs/39424717119): success after protected configuration was provisioned.
- [Full reachable-history scan](https://github.com/jryski/Household-OS/actions/runs/39425210118): success at `cbc71b166eb654ecd1b80208211bd68a0cd8b9cf` under that policy and the pinned scanner.

## Merge enforcement

Public ruleset `24057309` was read back after activation. It remains active for the default branch, preserves the existing pull-request/deletion/non-fast-forward protections, and requires:

- status context `LEAK-01`;
- GitHub Actions integration `15368`;
- strict up-to-date required checks.

No bypass actor was added. Publisher restriction to GitHub Actions does not alone identify one tamper-proof workflow; independent review of workflow and policy changes remains necessary.

## Scope and limits

The historical success concerns the fetched reachable references and supported Git objects within the recorded run's budgets. It does not certify deleted/unreachable objects, external LFS or submodule data, workflow logs, releases, third-party copies, or files never committed. Detection remains bounded by the configured private policy and scanner rules. Future changes require a new exact-head result.
