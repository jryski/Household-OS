# Household OS status

Updated September 7, 2026. See the [program checkpoint](https://github.com/WireSpeedComputing/sovereign-ai-os/blob/docs/wirespeed-public-state-20260907/CURRENT-STATUS.md).

Household OS turns permitted long-lived context into household planning, preparation, coordination and approved action. Calendar intake and delivery are early working slices, not the whole product.

The public repository contains calendar reconciliation code, synthetic fixtures and deployment guidance. Private operation is not evidence that every fresh assistant can find or use it. A reported session searched the wrong store, skipped startup discovery and incorrectly concluded the household feature was unimplemented.

The repair is published in [draft PR 4](https://github.com/jryski/Household-OS/pull/4): an explicit HOUSE read path performs startup discovery before a date-scoped day brief, rejects stale or invalid capability information, and preserves scoped coverage. All 68 offline tests passed on the local review candidate. It is not merged or deployed. Mobile and voice clients still need an authorized integration with this path; the original field failure is not yet proven resolved.

No real household records, production identifiers or private operational receipts belong here. Viewer filters and shared operator credentials are not principal-bound authorization. Live deployment, multi-user authorization and release acceptance remain separately gated.
