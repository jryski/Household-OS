"""Compile a synthetic maintenance proposal and bounded worker research packet.

This module has no network, database, credential, scheduler, or acceptance code.
The existing authenticated worker owns transport, leases and submission. The
optional callback only prepares an artifact through a host-supplied writer.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Callable
from uuid import UUID


MAX_BYTES = 16_384
_AUTHORITY = "research_only"
_UNKNOWN = {"model": None, "last_service_at": None, "service_status": "unknown"}


class WorkflowError(ValueError):
    """Fixed error code; never includes input records or transport output."""


def _bounded(value: object, limit: int = MAX_BYTES) -> bytes:
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise WorkflowError("invalid_json") from None
    if len(raw) > limit:
        raise WorkflowError("byte_budget_exceeded")
    return raw


def _keys(value: object, expected: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise WorkflowError("invalid_fields")


def _text(value: object, limit: int) -> str:
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or len(value.encode("utf-8")) > limit
            or any(ord(char) < 32 for char in value)):
        raise WorkflowError("invalid_text")
    return value


def _reference(value: object) -> str:
    value = _text(value, 2000)
    if ":" not in value or any(char.isspace() for char in value):
        raise WorkflowError("invalid_reference")
    return value


def _uuid(value: object) -> str:
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise WorkflowError("invalid_identifier") from None
    return value


def validate_manifest(value: dict) -> dict:
    """Accept this version's synthetic baseline, not arbitrary RPC instructions."""
    _bounded(value)
    _keys(value, {"contract", "synthetic", "workflow_id", "scenario_id", "demo",
                  "proposal", "observations", "evidence", "requested_evidence",
                  "acceptance_criteria", "finding_ref"})
    if value["contract"] != "household-maintenance-workflow/1" or value["synthetic"] is not True:
        raise WorkflowError("synthetic_manifest_required")
    for field in ("workflow_id", "scenario_id"):
        _text(value[field], 120)
        if "demo" not in value[field]:
            raise WorkflowError("demo_identity_required")
    demo, proposal, evidence = value["demo"], value["proposal"], value["evidence"]
    _keys(demo, {"board_id", "board_key", "item_id", "link_id", "observed_at"})
    for field in ("board_id", "item_id", "link_id"):
        if not _uuid(demo[field]).startswith("00000000-0000-4000-8000-"):
            raise WorkflowError("demo_identifier_required")
    if len({demo["board_id"], demo["item_id"], demo["link_id"]}) != 3:
        raise WorkflowError("duplicate_demo_identifier")
    _text(demo["board_key"], 120)
    if not demo["board_key"].endswith("-demo"):
        raise WorkflowError("demo_board_required")
    try:
        instant = datetime.fromisoformat(demo["observed_at"].replace("Z", "+00:00"))
        if instant.tzinfo is None:
            raise ValueError()
    except (TypeError, ValueError, AttributeError):
        raise WorkflowError("invalid_demo_timestamp") from None
    _keys(proposal, {"item_key", "title", "description", "source_ref", "actor_ref",
                     "domains", "due_at", "not_before", "confidence"})
    for field, limit in (("item_key", 500), ("title", 300), ("description", 4096), ("actor_ref", 120)):
        _text(proposal[field], limit)
    if not proposal["item_key"].startswith("demo:") or not proposal["actor_ref"].startswith("agent-demo-"):
        raise WorkflowError("demo_attribution_required")
    if (proposal["due_at"] is not None or proposal["not_before"] is not None
            or proposal["confidence"] is not None or value["observations"] != _UNKNOWN):
        raise WorkflowError("baseline_unknowns_required")
    if proposal["domains"] != ["maintenance"]:
        raise WorkflowError("maintenance_domain_required")
    _keys(evidence, {"reference", "source_store", "source_kind", "source_key", "summary"})
    for field in ("source_store", "source_kind"):
        _text(evidence[field], 120)
    _text(evidence["source_key"], 512)
    _text(evidence["summary"], 1200)
    for ref in (proposal["source_ref"], evidence["reference"], value["finding_ref"]):
        if not _reference(ref).startswith("demo:"):
            raise WorkflowError("demo_reference_required")
    if proposal["source_ref"] != evidence["reference"]:
        raise WorkflowError("source_reference_mismatch")
    # Runtime context exposes locators only up to 512 characters; keep this
    # fixture representable without the broker's explicit omission fallback.
    _text(proposal["source_ref"], 512)
    _text(value["requested_evidence"], 600)
    criteria = value["acceptance_criteria"]
    if not isinstance(criteria, list) or not 1 <= len(criteria) <= 8:
        raise WorkflowError("invalid_acceptance_criteria")
    for criterion in criteria:
        _text(criterion, 500)
    return deepcopy(value)


def _finding(manifest: dict) -> dict:
    return {
        "contract": "household-maintenance-finding/1", "synthetic": True,
        "workflow_id": manifest["workflow_id"], "scenario_id": manifest["scenario_id"],
        "status": "proposed", "accepted": False, "external_action_authorized": False,
        "blocked": True, "reference": manifest["finding_ref"],
        "summary": "Maintenance timing cannot be established: equipment model and last-service date are unknown.",
        "observations": deepcopy(manifest["observations"]),
        "requested_evidence": manifest["requested_evidence"],
        "evidence_refs": [manifest["evidence"]["reference"]],
        "coverage": "Synthetic request only; source documents, other stores and external sources have not been checked.",
        "proposed_next_step": "Request the missing evidence, then research applicable manufacturer guidance before proposing maintenance timing.",
    }


def compile_workflow(value: dict) -> dict:
    """Prepare exact existing proposal arguments and display/research fixtures."""
    manifest = validate_manifest(value)
    demo, p, e = manifest["demo"], manifest["proposal"], manifest["evidence"]
    arguments = {"p_board_key": demo["board_key"], "p_item_key": p["item_key"],
                 "p_title": p["title"], "p_source_ref": p["source_ref"],
                 "p_actor_ref": p["actor_ref"], "p_description": p["description"],
                 "p_domains": p["domains"], "p_due_at": None, "p_not_before": None,
                 "p_confidence": None}
    link = {"board_id": demo["board_id"], "item_id": demo["item_id"],
            "relation": "evidence", "source_store": e["source_store"],
            "source_kind": e["source_kind"], "source_key": e["source_key"],
            "evidence_ref": e["reference"], "observed_at": demo["observed_at"]}
    evidence = {"id": demo["link_id"], **{k: v for k, v in link.items()
                if k not in {"board_id", "item_id"}},
                "references_omitted": False, "created_at": demo["observed_at"]}
    item = {"id": demo["item_id"], "title": p["title"], "description": p["description"],
            "description_truncated": False, "state": "proposed", "version": 1,
            "source_ref": p["source_ref"], "source_ref_omitted": False,
            "due_at": None, "not_before": None, "lease_until": None}
    context = {"contract": "household-maintenance-research-context/1", "synthetic": True,
               "contentTrust": "untrusted", "authority": _AUTHORITY,
               "workflow_id": manifest["workflow_id"], "scenario_id": manifest["scenario_id"],
               "item": item, "observations": manifest["observations"],
               "evidence": [{"reference": e["reference"], "summary": e["summary"]}],
               "requested_evidence": manifest["requested_evidence"],
               "acceptance_criteria": manifest["acceptance_criteria"],
               "coverage": {"external_sources_checked": False, "other_stores_checked": False,
                            "omitted_sections": []}}
    result = {"contract": "household-maintenance-package/1", "synthetic": True,
              "workflow_id": manifest["workflow_id"], "scenario_id": manifest["scenario_id"],
              "proposal": {"operation": "life_propose_work_v1", "arguments": arguments,
                           "dispatched": False},
              "item_links": [link],
              "preview": {"item": item, "evidence": [evidence], "dependencies": [], "activity": []},
              "worker_context": context, "proposed_finding": _finding(manifest),
              "preparation_only": True,
              "identity_note": "All preview IDs and the clock are invented. Proposal RPC returns a new canonical item ID; these preview IDs are not insertion arguments. Actor text is attribution, not identity or authority."}
    _bounded(context)
    _bounded(result)
    return deepcopy(result)


@dataclass(frozen=True)
class WorkflowBinding:
    """Runtime-supplied applicability binding; it grants no authentication."""
    board_id: str
    item_id: str
    source_ref: str

    def __post_init__(self):
        _uuid(self.board_id)
        _uuid(self.item_id)
        _reference(self.source_ref)


def prepare_finding(packet: dict, value: dict, binding: WorkflowBinding) -> dict:
    """Consume an existing worker's research callback packet, without dispatch."""
    manifest = validate_manifest(value)
    _bounded(packet, MAX_BYTES + 4096)
    if not isinstance(packet, dict) or packet.get("authority") != _AUTHORITY or packet.get("contentTrust") != "untrusted":
        raise WorkflowError("research_packet_required")
    context = packet.get("context")
    if not isinstance(context, dict) or context.get("contract") != "life-runtime-context/1":
        raise WorkflowError("runtime_context_required")
    _bounded(context)
    item, scope = context.get("item"), context.get("scope")
    if (not isinstance(item, dict) or not isinstance(scope, dict)
            or scope.get("board_id") != binding.board_id or item.get("id") != binding.item_id
            or item.get("source_ref") != binding.source_ref
            or binding.source_ref != manifest["proposal"]["source_ref"]):
        raise WorkflowError("workflow_context_mismatch")
    if (item.get("state") != "researching" or item.get("description_truncated") is not False
            or item.get("source_ref_omitted") is not False
            or type(item.get("version")) is not int or item["version"] < 1
            or packet.get("item_version") != item["version"]):
        raise WorkflowError("current_research_context_required")
    if item.get("description") != manifest["proposal"]["description"]:
        raise WorkflowError("workflow_proposal_changed")
    for section in ("evidence", "dependencies", "activity"):
        if not isinstance(context.get(section), list) or len(context[section]) > 20:
            raise WorkflowError("bounded_context_required")
    coverage = context.get("coverage")
    if (not isinstance(coverage, dict) or any(coverage.get(field) != 0 for field in
            ("evidence_omitted", "dependencies_omitted", "activity_omitted"))):
        raise WorkflowError("complete_context_required")
    if not any(isinstance(row, dict) and row.get("evidence_ref") == binding.source_ref
               and row.get("references_omitted") is False for row in context["evidence"]):
        raise WorkflowError("workflow_evidence_missing")
    result = _finding(manifest)
    result["provenance"] = {"item_id": binding.item_id, "item_version": item["version"],
                            "context_id": _text(packet.get("context_id"), 128)}
    _bounded(result)
    return result


def make_researcher(value: dict, *, binding: WorkflowBinding,
                    persist_finding: Callable[[dict], str], finding_factory: Callable) -> Callable:
    """Adapt to WorkplaneWorker.research; host supplies storage and Finding type.

    No private runtime import or path discovery. The authenticated worker still
    validates current scope/lease before and after calling this callback. This
    function neither prepares nor submits an attempt and never retries writes.
    """
    manifest = validate_manifest(value)

    def researcher(packet: dict):
        artifact = prepare_finding(packet, manifest, binding)
        reference = _reference(persist_finding(deepcopy(artifact)))
        return finding_factory(reference=reference, blocked=True)

    return researcher


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare a synthetic maintenance workflow; no database or transport calls.")
    parser.add_argument("command", choices=("prepare",))
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", type=Path, help="New JSON file; existing files are never overwritten")
    args = parser.parse_args(argv)
    try:
        with args.manifest.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise WorkflowError("byte_budget_exceeded")
        result = compile_workflow(json.loads(raw))
        rendered = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(rendered)
        else:
            print(rendered, end="")
    except (OSError, ValueError, UnicodeError) as exc:
        code = str(exc) if isinstance(exc, WorkflowError) else "workflow_preparation_failed"
        parser.exit(2, f"{code}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
