# Security policy

Household OS is a public reference implementation with synthetic fixtures. It must never contain real household data.

## Report a vulnerability privately

Use this repository's private vulnerability reporting form:
<https://github.com/jryski/Household-OS/security/advisories/new>

If the form is unavailable, email **jryski@gmail.com** instead.

Do not put exploit details, credentials, tokens, private hostnames or real
personal, household, business or customer records in a public issue, pull
request, discussion or CI log. Use synthetic examples and redacted output.

Where you can, include:

- the affected commit, tag or file;
- preconditions and the trust boundary involved;
- a minimal reproduction using synthetic data;
- demonstrated and likely impact;
- whether secrets or personal data were exposed; and
- a proposed mitigation, if known.

Never attach real household records, calendar IDs, provider object IDs or
provider tokens, even privately, unless the maintainers ask for a specific
redacted artifact.

## Supported versions

No production release of Household OS is supported. `main` and tagged pre-releases
are maintained on a best-effort basis.

## Other components

Each repository in the program has its own private reporting form. If the issue
is in another component, report it there. The
[program map](https://github.com/WireSpeedComputing/sovereign-ai-os) lists
every component.

