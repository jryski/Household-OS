## Summary

<!-- What changed, and which issue it follows. -->

## Docs or code

- [ ] Docs / templates only
- [ ] Code, schema, or other non-docs change (not covered by the docs-only merge policy)

## Privacy boundary

- [ ] No real HOUSE or VAULT records, personal data, health data, or finance data
- [ ] No credentials, tokens, keys, private topology, or provider object IDs
- [ ] Examples and fixtures use synthetic identifiers only (`person-1`, `agent-1`, and similar)

## DCO

- [ ] Every commit is signed with `git commit -s` (`Signed-off-by`), per [DCO.md](https://github.com/jryski/Household-OS/blob/main/DCO.md)

## Docs-only merge reminder (D3)

Docs-only pull requests merge only after CI is green and an independent
reviewer who is not the author has approved. The author does not merge their
own pull request. A bot check or a non-docs change is not a merge claim.

- [ ] I will not merge this pull request myself
- [ ] If this is docs-only: wait for green CI and a reviewer who is not the author

## Gate

<!-- Gate A (safe contributor / public docs), Gate B (synthetic read-only), or Gate C (separately authorized real-user deploy). Gate C needs its own authorization and is not implied by A or B. -->

- Gate:
