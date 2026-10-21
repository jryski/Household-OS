# Synthetic furnace evidence intake

This Gate B example answers the furnace baseline's evidence request with an
invented equipment-label photo and an invented service receipt. It turns each
supplied file into a digest-verified evidence reference and a **proposed**
finding for a person to review. Every value here is fabricated. The two files
are generated in code, depict no real device and are not real records.
Tracked in [issue #41](https://github.com/jryski/Household-OS/issues/41), as a
small source slice of the intake storage work in
[issue #15](https://github.com/jryski/Household-OS/issues/15).

The [baseline](../furnace-baseline/README.md) manifest, prepared fixture and
blocked finding stay frozen. Evidence is added beside them through new
references and a separately versioned finding that `responds_to` the baseline
finding. Nothing rewrites the baseline to make new facts look previously known.

## Prepare the example

From the repository root, using Python 3.11 or newer:

```sh
PYTHONPATH=src python -m household_os.maintenance_evidence demo \
  --manifest examples/maintenance/furnace-baseline/manifest.json \
  --intake examples/maintenance/furnace-evidence/intake.json
```

`--output /path/to/new.json` writes a new file and refuses to overwrite one.
The demo uses an in-memory synthetic store. It has no storage, database,
credential, network, OCR or model access. [`prepared.json`](prepared.json) is the
reproducible output.

## What is kept separate

| Layer | Where | Meaning |
| --- | --- | --- |
| Possession | `proposed_finding.possession` | A person supplied these bytes. Digest, size and media type were checked before storage and again on read. |
| Claims | `proposed_finding.claims` | Values a person transcribed or an extractor suggested. Always `unconfirmed`, never accepted. |
| Unsupported claims | `proposed_finding.unsupported_claims` | Claims an artifact cannot support, malformed dates, or conflicting values. Only the field name is kept. The value stays unknown. |
| Proposal | `proposed_finding.proposed_observations` | The unconfirmed values a reviewer can confirm or correct. `service_status` stays `unknown`. |
| Approval | `proposed_finding.confirmed_facts` | Always empty here. Only a person, through the review desk, confirms facts. |

A label photo can propose a `model`; it never establishes a service date. A
receipt can propose a calendar-date `last_service_at`; it does not establish
equipment identity. Partial, relative or timed dates are not accepted as dates.
The finding remains `blocked`, `accepted: false`, with no external action.
Either artifact, or both, may be absent; the missing ones are listed.

## Output shapes

| Field | Reused contract |
| --- | --- |
| `ingest_sources` | The documented `ingest_source` fields (`source_kind`, `source_ref`, `source_sha256`, provenance). Prepared shapes without database IDs; `document_date`, `parser_*` and `confidence` stay null and `parse_status` is `needs_review`. |
| `item_links` | The existing `life_ops.item_links` evidence row. `source_key` is `sha256:<digest>`, so repeating the same bytes maps to the same unique key. No link-insertion RPC is invented or called. |
| `already_linked` | Repeat intake: links the host already holds. They are not prepared again. |
| `research_evidence` | Fixed-template locator summaries. Source contents are untrusted and are not copied into worker text. |
| `handoff` | Plain English: what was supplied, what it supports, what is missing and what storage work remains. |

The public schema does not create the deployment's ingest-source table. Its
logical shape comes from [image calendar intake](../../../docs/IMAGE_CALENDAR_INTAKE.md).
Column names beyond that documented shape are not guessed.

## Storage boundary

`prepare_evidence` writes only through a host-supplied store implementing
`AuthorizedEvidenceStore`: `store_name`, the single authorized `board_id`, a
content-addressed idempotent `put(sha256=, media_type=, data=)` returning an
opaque reference, and `read(reference)`. Requests cannot name a path, URL or
bucket. A reference that looks like a URL or filesystem path is refused, as are
a store authorized for another board, a declared digest that does not match the
bytes, stored bytes that fail verification on read, an unexpected media type or
leading bytes, and files outside 1 byte to 8 MiB.

Private storage, short-lived signed access, deployment verify-on-read, expiry
purge and an off-platform backup target remain open under issue #15. This
example activates none of them.

## Feed the existing worker

After an authorized path inserts the prepared links, the existing runtime
context carries them as ordinary evidence rows. `prepare_evidence_finding(packet,
manifest, package, binding)` runs the baseline packet checks unchanged, requires
every prepared link to be present and unomitted, and returns the proposed
finding with provenance. It adds no worker tool and no source download.

Run the focused offline checks with:

```sh
PYTHONPATH=src python -m unittest discover -s tests -p 'test_maintenance_*.py' -v
```
