# Synthetic furnace maintenance baseline

This Gate B example prepares a useful first maintenance task using existing
proposed-work, source-link and worker-research contracts. Every identifier, request
and timestamp here is invented. It represents no actual equipment or household.
It introduces no asset/person tables and installs no routine or schedule.
Tracked in [issue #39](https://github.com/jryski/Household-OS/issues/39).

The task is **Establish furnace maintenance baseline**. The model and last-service
date are unknown; maintenance timing and service status cannot be established.
The one specific request is:

> Provide a readable manufacturer/model-label photo and the most recent service
> receipt, if available.

The demo does not select a maintenance interval, infer overdue work, claim that
service occurred, or supply equipment repair instructions.

## Prepare the shared fixture

From the repository root, using Python 3.11 or newer:

```sh
PYTHONPATH=src python -m household_os.maintenance_workflow prepare \
  --manifest examples/maintenance/furnace-baseline/manifest.json
```

Add `--output /path/to/new-prepared.json` to write a new file. Existing files are
refused. This command reads only the specified local manifest and writes JSON.
It has no connection options, database clients, credentials or network requests.
The installed entry point is `household-maintenance-workflow`.

[`prepared.json`](prepared.json) is the reproducible UI preview and integration
fixture generated from [`manifest.json`](manifest.json). The compact JSON package
and its research context each fit within 16,384 UTF-8 bytes. Oversized input or
output fails rather than silently dropping evidence.

| Output field | Consumer and meaning |
| --- | --- |
| `proposal` | Exact ten argument names for existing `life_propose_work_v1`; `dispatched` is false. This is a prepared request, not an insert receipt. |
| `item_links` | Existing `life_ops.item_links` row shape with synthetic board/item references. No link-insertion RPC is invented or called. |
| `preview` | Existing runtime item/evidence/dependency/activity shapes for a clearly synthetic UI view. The item remains `proposed`, version 1. |
| `worker_context` | Bounded task, explicit unknowns, evidence locator/summary, one evidence request and acceptance criteria. Content is untrusted and authority is research only. |
| `proposed_finding` | A blocked proposal, with `accepted: false`, for requesting missing evidence. No accepted outcome or external action. |

The preview is not an authenticated runtime response: it has no principal, client,
grant or lease token. Its invented item ID is not an argument to the proposal RPC.
The RPC generates the canonical ID if an authorized ingestion path later creates
the proposal. Preview IDs must not be substituted for real provider/database IDs.
The actor string records invented attribution and grants no authority.

## Feed the existing worker

Public Household OS code does not import or discover a private runtime. Its
`make_researcher` callback factory accepts a host-supplied artifact writer and
Finding factory. The existing authenticated `WorkplaneWorker` owns check-in,
context retrieval, research leases, current scope checks and submission. A
proposal cannot be claimed until a separate authorized decision makes it ready.

The runtime can adapt this callback explicitly, after its normal authenticated
preparation step. The following is an integration sketch, not an executable
deployment or a credential setup path:

```python
from household_os.maintenance_workflow import WorkflowBinding, make_researcher

researcher = make_researcher(
    manifest,
    binding=WorkflowBinding(
        board_id=trusted_runtime_board_id,
        item_id=canonical_proposal_item_id,
        source_ref=manifest["proposal"]["source_ref"],
    ),
    persist_finding=approved_artifact_store.put_json,
    finding_factory=Finding,  # Existing runtime type; host imports it explicitly.
)
worker.research(researcher)   # Requires the worker's current authenticated lease.
# A separate intentional worker.submit() would submit the blocked finding.
```

`prepare_finding(packet, manifest, binding)` is also available for a runtime that
wants a JSON-compatible artifact before adapting it. It checks applicability to
the trusted item/board/source binding, matching version and description, current
research state, evidence presence and complete bounded sections. These checks do
not authenticate a user or replace the broker's grant/session checks. References
remain locators; this module does not fetch or verify their source documents.

The artifact writer must durably store the finding and return its locator. The
callback returns that locator with `blocked=True` through the supplied Finding
type. It never calls acceptance, submission, scheduling or a provider. Storage
errors propagate; the callback does not retry. If persistence or submission has
an uncertain outcome, use the runtime's reconciliation path before another
intentional attempt.

Run the focused offline checks with:

```sh
PYTHONPATH=src python -m unittest discover -s tests -p test_maintenance_workflow.py -v
```

See [the work-plane implementation](../../../docs/LIFE_ASSISTANCE_WORK_PLANE.md)
and [the authenticated runtime contract](../../../docs/LIFE_RUNTIME_ADAPTER.md).
This source package does not activate either layer or exercise a live database.
