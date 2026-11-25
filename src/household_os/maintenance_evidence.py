"""Turn person-supplied maintenance artifacts into digest-verified evidence references.

Source preparation only. This module has no network, database, credential,
OCR, model, scheduler or acceptance code. Bytes are written only through a
host-supplied authorized store; callers cannot name a path, URL or bucket.
Nothing here turns an extracted claim into an accepted fact.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
import struct
from typing import Mapping, Protocol, Sequence
import zlib

from household_os.maintenance_workflow import (
    MAX_BYTES, WorkflowBinding, WorkflowError, _bounded, _keys, _text,
    _uuid, prepare_finding, validate_manifest,
)


MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
MAX_CLAIMS = 8
# Artifact roles requested by the baseline workflow. Media types are explicit;
# the leading bytes must agree with the declared type.
KINDS = {
    "equipment_label_photo": {
        "label": "equipment label photo", "link_kind": "equipment-label-photo",
        "media": ("image/jpeg", "image/png"), "fields": ("model",)},
    "service_receipt": {
        "label": "service receipt", "link_kind": "service-receipt",
        "media": ("image/jpeg", "image/png", "application/pdf"), "fields": ("last_service_at",)},
}
_MAGIC = {"image/jpeg": b"\xff\xd8\xff", "image/png": b"\x89PNG\r\n\x1a\n", "application/pdf": b"%PDF-"}
_INGEST_KIND = {"image/jpeg": "image", "image/png": "image", "application/pdf": "pdf"}
_ORIGINS = ("person_transcription", "automated_extraction")
# Opaque store references: a lowercase namespace, a colon, then only
# letters, digits and ``:._-``. No slash, backslash, tilde, query or space,
# so URLs, bucket URIs and filesystem paths cannot match.
_STORE_REFERENCE = re.compile(r"[a-z][a-z0-9-]{0,31}:[A-Za-z0-9:._-]+")
_RESERVED_SCHEMES = frozenset({"data", "file", "ftp", "ftps", "gs", "http", "https", "javascript",
                               "s3", "sftp", "smb", "ssh", "urn", "ws", "wss"})
_UNSUPPORTED_REASONS = ("field_not_supported_by_artifact", "value_not_a_calendar_date")
_REMAINING = ("Private storage, short-lived signed access, verify-on-read in the deployment, "
              "expiry purge and an off-platform backup target remain separate deployment work.")


class AuthorizedEvidenceStore(Protocol):
    """Host-supplied storage boundary; it owns custody, not this module.

    ``board_id`` is the single board the host authorized this store for.
    ``put`` must be content-addressed and idempotent: the same digest returns
    the same opaque reference. ``read`` returns the stored bytes for that
    reference. References must match an allowlisted opaque form
    (``namespace:token``, letters, digits and ``:._-`` only, at most 512 bytes,
    no reserved URL scheme). Anything shaped like a URL, bucket URI or path is
    refused, so signed URLs, bucket names and paths cannot cross this boundary.
    """
    store_name: str
    board_id: str

    def put(self, *, sha256: str, media_type: str, data: bytes) -> str: ...

    def read(self, reference: str) -> bytes: ...


def sha256_hex(data: bytes) -> str:
    if not isinstance(data, (bytes, bytearray)):
        raise WorkflowError("artifact_bytes_required")
    return hashlib.sha256(bytes(data)).hexdigest()


def _digest(value: object) -> str:
    if (not isinstance(value, str) or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise WorkflowError("invalid_digest")
    return value


def _instant(value: object) -> str:
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if instant.tzinfo is None:
            raise ValueError()
    except (TypeError, ValueError, AttributeError):
        raise WorkflowError("invalid_timestamp") from None
    return value


def _store_reference(value: object) -> str:
    if (not isinstance(value, str) or len(value.encode("utf-8")) > 512
            or not _STORE_REFERENCE.fullmatch(value)
            or value.split(":", 1)[0] in _RESERVED_SCHEMES):
        raise WorkflowError("opaque_store_reference_required")
    return value


def validate_intake(value: dict, manifest: dict) -> dict:
    """Accept only the declared artifact descriptors; bytes travel separately."""
    _bounded(value)
    _keys(value, {"contract", "synthetic", "workflow_id", "scenario_id", "received_at", "artifacts"})
    if value["contract"] != "household-maintenance-evidence-intake/1" or value["synthetic"] is not True:
        raise WorkflowError("synthetic_intake_required")
    if value["workflow_id"] != manifest["workflow_id"] or value["scenario_id"] != manifest["scenario_id"]:
        raise WorkflowError("workflow_scope_mismatch")
    _instant(value["received_at"])
    artifacts = value["artifacts"]
    if not isinstance(artifacts, list) or len(artifacts) > len(KINDS):
        raise WorkflowError("invalid_artifacts")
    seen = set()
    for artifact in artifacts:
        _keys(artifact, {"kind", "media_type", "declared_sha256", "claims"})
        kind = artifact["kind"]
        if kind not in KINDS or kind in seen:
            raise WorkflowError("unsupported_artifact_kind")
        seen.add(kind)
        if artifact["media_type"] not in KINDS[kind]["media"]:
            raise WorkflowError("unsupported_media_type")
        _digest(artifact["declared_sha256"])
        claims = artifact["claims"]
        if not isinstance(claims, list) or len(claims) > MAX_CLAIMS:
            raise WorkflowError("invalid_claims")
        for claim in claims:
            _keys(claim, {"field", "value", "origin"})
            _text(claim["field"], 64)
            _text(claim["value"], 120)
            if claim["origin"] not in _ORIGINS:
                raise WorkflowError("invalid_claim_origin")
    return deepcopy(value)


def _check_bytes(artifact: dict, data: object) -> tuple[str, int]:
    if not isinstance(data, (bytes, bytearray)):
        raise WorkflowError("artifact_bytes_required")
    data = bytes(data)
    if not 1 <= len(data) <= MAX_ARTIFACT_BYTES:
        raise WorkflowError("artifact_size_out_of_bounds")
    if not data.startswith(_MAGIC[artifact["media_type"]]):
        raise WorkflowError("media_type_mismatch")
    digest = sha256_hex(data)
    if digest != artifact["declared_sha256"]:
        raise WorkflowError("digest_mismatch")
    return digest, len(data)


def _claim_value(field: str, value: str):
    if field == "last_service_at":
        # Date semantics only; partial, relative or timed values stay unknown.
        try:
            if len(value) != 10 or date.fromisoformat(value).isoformat() != value:
                raise ValueError()
        except ValueError:
            return None
    return value


def _check_artifact(artifact: dict, data: object, *, manifest: dict, binding: WorkflowBinding,
                    store: AuthorizedEvidenceStore) -> tuple[str, int, str]:
    """Every refusal this module can decide on its own, before any store call."""
    if binding.source_ref != manifest["proposal"]["source_ref"]:
        raise WorkflowError("workflow_context_mismatch")
    if getattr(store, "board_id", None) != binding.board_id:
        raise WorkflowError("store_scope_mismatch")
    store_name = _text(getattr(store, "store_name", None), 120)
    digest, size = _check_bytes(artifact, data)
    return digest, size, store_name


def _verify_stored(store: AuthorizedEvidenceStore, reference: str, digest: str, error: str) -> None:
    try:
        stored = store.read(reference)
    except Exception:
        raise WorkflowError(error) from None
    if not isinstance(stored, (bytes, bytearray)) or sha256_hex(stored) != digest:
        raise WorkflowError(error)


def _record(artifact: dict, *, digest: str, size: int, store_name: str, reference: str,
            manifest: dict, binding: WorkflowBinding, received_at: str) -> dict:
    spec = KINDS[artifact["kind"]]
    ingest_source = {
        "source_kind": _INGEST_KIND[artifact["media_type"]], "source_ref": reference,
        "source_sha256": digest, "source_label": f"Person-supplied {spec['label']}",
        "observed_at": received_at, "document_date": None, "parser_agent": None,
        "parser_version": None, "parse_status": "needs_review", "confidence": None,
        "metadata": {"artifact_kind": artifact["kind"], "media_type": artifact["media_type"],
                     "byte_length": size, "workflow_id": manifest["workflow_id"],
                     "synthetic": True},
    }
    link = {"board_id": binding.board_id, "item_id": binding.item_id, "relation": "evidence",
            "source_store": store_name, "source_kind": spec["link_kind"],
            "source_key": "sha256:" + digest, "evidence_ref": reference, "observed_at": received_at}
    possession = {"artifact_kind": artifact["kind"], "evidence_ref": reference,
                  "source_sha256": digest, "byte_length": size,
                  "media_type": artifact["media_type"], "digest_verified_on_read": True}
    claims, unsupported = [], []
    for claim in artifact["claims"]:
        value = _claim_value(claim["field"], claim["value"]) if claim["field"] in spec["fields"] else None
        if value is None:
            reason = "field_not_supported_by_artifact" if claim["field"] not in spec["fields"] else "value_not_a_calendar_date"
            unsupported.append({"field": claim["field"], "artifact_kind": artifact["kind"], "reason": reason})
        else:
            claims.append({"field": claim["field"], "value": value, "artifact_kind": artifact["kind"],
                           "evidence_ref": reference, "origin": claim["origin"], "status": "unconfirmed"})
    return {"ingest_source": ingest_source, "item_link": link, "possession": possession,
            "claims": claims, "unsupported_claims": unsupported}


def intake_artifact(artifact: dict, data: bytes, *, manifest: dict, binding: WorkflowBinding,
                    store: AuthorizedEvidenceStore, received_at: str) -> dict:
    """Verify, store through the host boundary, read back and prepare existing row shapes."""
    digest, size, store_name = _check_artifact(artifact, data, manifest=manifest, binding=binding, store=store)
    reference = _store_reference(store.put(sha256=digest, media_type=artifact["media_type"], data=bytes(data)))
    _verify_stored(store, reference, digest, "stored_digest_mismatch")
    return _record(artifact, digest=digest, size=size, store_name=store_name, reference=reference,
                   manifest=manifest, binding=binding, received_at=received_at)


def _link_key(link: dict) -> tuple:
    return (link.get("item_id"), link.get("relation"), link.get("source_store"),
            link.get("source_kind"), link.get("source_key"))


def prepare_evidence(manifest_value: dict, intake_value: dict, artifacts: Mapping[str, bytes], *,
                     binding: WorkflowBinding, store: AuthorizedEvidenceStore,
                     existing_links: Sequence[dict] = ()) -> dict:
    """Prepare evidence rows and a proposed finding; nothing is inserted or accepted.

    ``existing_links`` are item-link rows the host already holds for this item.
    A repeat of the same bytes maps to the same unique link key: it is verified
    by reading the existing reference, is not written again, and is reported as
    already linked instead of producing a second row.

    Every refusal this module decides (fields, scope, bytes, digest, duplicate
    bytes, existing-link scope, existing-reference conflict) happens before the
    first ``store.put``. Only a refusal of the store's own response (a
    non-opaque reference or failed verify-on-read) can follow a write; content
    addressing keeps that write idempotent, and this module never deletes.
    """
    manifest = validate_manifest(manifest_value)
    intake = validate_intake(intake_value, manifest)
    if binding.source_ref != manifest["proposal"]["source_ref"]:
        raise WorkflowError("workflow_context_mismatch")
    if getattr(store, "board_id", None) != binding.board_id:
        raise WorkflowError("store_scope_mismatch")
    declared = {artifact["kind"] for artifact in intake["artifacts"]}
    if not isinstance(artifacts, Mapping) or set(artifacts) != declared:
        raise WorkflowError("artifact_set_mismatch")
    existing = {}
    for row in existing_links:
        if not isinstance(row, dict) or row.get("item_id") != binding.item_id or row.get("board_id") != binding.board_id:
            raise WorkflowError("existing_link_scope_mismatch")
        existing[_link_key(row)] = row
    checked = [(artifact, *_check_artifact(artifact, artifacts[artifact["kind"]], manifest=manifest,
                                           binding=binding, store=store))
               for artifact in intake["artifacts"]]
    if len({digest for _, digest, _, _ in checked}) != len(checked):
        raise WorkflowError("duplicate_artifact_bytes")
    priors = []
    for artifact, digest, _, store_name in checked:
        key = (binding.item_id, "evidence", store_name, KINDS[artifact["kind"]]["link_kind"], "sha256:" + digest)
        prior = existing.get(key)
        if prior is not None:
            try:
                reference = _store_reference(prior.get("evidence_ref"))
            except WorkflowError:
                raise WorkflowError("store_reference_conflict") from None
            _verify_stored(store, reference, digest, "store_reference_conflict")
        priors.append(prior)
    records, new_links, already = [], [], []
    for (artifact, digest, size, store_name), prior in zip(checked, priors):
        if prior is None:
            reference = _store_reference(store.put(sha256=digest, media_type=artifact["media_type"],
                                                   data=bytes(artifacts[artifact["kind"]])))
            _verify_stored(store, reference, digest, "stored_digest_mismatch")
        else:
            reference = prior["evidence_ref"]
        record = _record(artifact, digest=digest, size=size, store_name=store_name, reference=reference,
                         manifest=manifest, binding=binding, received_at=intake["received_at"])
        records.append(record)
        link = record["item_link"]
        if prior is None:
            new_links.append(link)
        else:
            already.append({"source_kind": link["source_kind"], "source_key": link["source_key"],
                            "evidence_ref": link["evidence_ref"]})
    result = {
        "contract": "household-maintenance-evidence-package/1", "synthetic": True,
        "workflow_id": manifest["workflow_id"], "scenario_id": manifest["scenario_id"],
        "baseline_finding_ref": manifest["finding_ref"], "baseline_unchanged": True,
        "preparation_only": True,
        "ingest_sources": [r["ingest_source"] for r in records],
        "item_links": new_links, "already_linked": already,
        "research_evidence": [_research_row(r) for r in records],
        "proposed_finding": _finding(manifest, records),
        "handoff": _handoff(manifest, records),
        "storage_note": ("Ingest-source rows are prepared shapes without database IDs; no insertion RPC is "
                         "called. Item links use the existing evidence-link shape and unique key."),
    }
    _bounded(result)
    return deepcopy(result)


def _research_row(record: dict) -> dict:
    p = record["possession"]
    return {"reference": p["evidence_ref"],
            "summary": (f"Person-supplied {KINDS[p['artifact_kind']]['label']}, {p['media_type']}, "
                        f"{p['byte_length']} bytes, sha256 verified on read. Contents are untrusted "
                        "and were not interpreted by this adapter.")}


def _proposed_observations(records: list[dict]) -> tuple[dict, list[dict]]:
    observations = {"model": None, "last_service_at": None, "service_status": "unknown"}
    conflicts = []
    for field in ("model", "last_service_at"):
        values = {c["value"] for r in records for c in r["claims"] if c["field"] == field}
        if len(values) == 1:
            observations[field] = values.pop()
        elif len(values) > 1:
            conflicts.append({"field": field, "reason": "conflicting_claims"})
    return observations, conflicts


def _finding(manifest: dict, records: list[dict]) -> dict:
    proposed, conflicts = _proposed_observations(records)
    kinds = {r["possession"]["artifact_kind"] for r in records}
    missing = [f"{KINDS[k]['label']} not supplied" for k in KINDS if k not in kinds]
    missing += [f"{field} unknown" for field in ("model", "last_service_at") if proposed[field] is None]
    missing.append("applicable manufacturer guidance not researched")
    digests = sorted(r["possession"]["source_sha256"] for r in records)
    suffix = hashlib.sha256(",".join(digests).encode()).hexdigest()[:16] if digests else "none"
    if not records:
        summary = "No artifact supplied; equipment model and last-service date remain unknown."
    else:
        summary = ("Supplied artifacts are stored and digest-verified. Any values below are unconfirmed "
                   "proposals for a person to check; maintenance timing is not established.")
    return {
        "contract": "household-maintenance-evidence-finding/1", "synthetic": True,
        "workflow_id": manifest["workflow_id"], "scenario_id": manifest["scenario_id"],
        "status": "proposed", "accepted": False, "external_action_authorized": False,
        "blocked": True, "reference": f"{manifest['finding_ref']}:evidence:{suffix}",
        "responds_to": manifest["finding_ref"], "summary": summary,
        "possession": [r["possession"] for r in records],
        "claims": [c for r in records for c in r["claims"]],
        "unsupported_claims": [u for r in records for u in r["unsupported_claims"]] + conflicts,
        "proposed_observations": proposed,
        "confirmed_facts": {},
        "still_missing": missing,
        "evidence_refs": [manifest["evidence"]["reference"]] + [r["possession"]["evidence_ref"] for r in records],
        "proposed_next_step": ("A person compares the proposed values with the supplied artifacts and confirms or "
                               "corrects them through the review desk before any manufacturer research or timing proposal."),
    }


def _handoff(manifest: dict, records: list[dict]) -> dict:
    proposed, _ = _proposed_observations(records)
    supplied = [f"{KINDS[r['possession']['artifact_kind']]['label'].capitalize()} "
                f"({r['possession']['byte_length']} bytes, verified digest)" for r in records] or ["Nothing yet."]
    supports = []
    if proposed["model"] is not None:
        supports.append("The label photo is said to show model "
                        f"{json.dumps(proposed['model'], ensure_ascii=True)} (quoted untrusted claim, unconfirmed).")
    if proposed["last_service_at"] is not None:
        supports.append("The receipt is said to show service on "
                        f"{json.dumps(proposed['last_service_at'], ensure_ascii=True)} (quoted untrusted claim, unconfirmed).")
    supports.append("Service status stays unknown; no artifact establishes whether service is due.")
    return {"contentTrust": "untrusted", "supplied": supplied, "supports": supports,
            "missing": _finding(manifest, records)["still_missing"], "remaining_storage_work": _REMAINING}


def _rebuild_records(finding: object, verified: list[dict]) -> list[dict]:
    """Re-derive the evidence records from validated fields only.

    Status, acceptance, blocking, confirmed facts, authorization flags and any
    unknown keys in the supplied finding are never read; ``_finding`` sets them.
    """
    if not isinstance(finding, dict):
        raise WorkflowError("evidence_finding_required")
    possession, claims, unsupported = (finding.get(k) for k in ("possession", "claims", "unsupported_claims"))
    if not all(isinstance(v, list) for v in (possession, claims, unsupported)) or len(possession) > len(KINDS):
        raise WorkflowError("invalid_evidence_finding")
    records, kinds = [], set()
    for row in possession:
        _keys(row, {"artifact_kind", "evidence_ref", "source_sha256", "byte_length", "media_type",
                    "digest_verified_on_read"})
        kind = row["artifact_kind"]
        if kind not in KINDS or kind in kinds or row["media_type"] not in KINDS[kind]["media"]:
            raise WorkflowError("invalid_evidence_finding")
        kinds.add(kind)
        digest, reference = _digest(row["source_sha256"]), _store_reference(row["evidence_ref"])
        if (type(row["byte_length"]) is not int or not 1 <= row["byte_length"] <= MAX_ARTIFACT_BYTES
                or row["digest_verified_on_read"] is not True):
            raise WorkflowError("invalid_evidence_finding")
        if not any(link["source_kind"] == KINDS[kind]["link_kind"] and link["source_key"] == "sha256:" + digest
                   and link["evidence_ref"] == reference for link in verified):
            raise WorkflowError("prepared_evidence_missing")
        records.append({"possession": {"artifact_kind": kind, "evidence_ref": reference, "source_sha256": digest,
                                       "byte_length": row["byte_length"], "media_type": row["media_type"],
                                       "digest_verified_on_read": True},
                        "claims": [], "unsupported_claims": []})
    if len(records) != len(verified):
        raise WorkflowError("prepared_evidence_missing")
    by_kind = {r["possession"]["artifact_kind"]: r for r in records}
    if len(claims) > MAX_CLAIMS * len(KINDS) or len(unsupported) > MAX_CLAIMS * len(KINDS) + 2:
        raise WorkflowError("invalid_evidence_finding")
    for claim in claims:
        _keys(claim, {"field", "value", "artifact_kind", "evidence_ref", "origin", "status"})
        record = by_kind.get(claim["artifact_kind"])
        if (record is None or claim["evidence_ref"] != record["possession"]["evidence_ref"]
                or claim["field"] not in KINDS[claim["artifact_kind"]]["fields"]
                or claim["origin"] not in _ORIGINS):
            raise WorkflowError("invalid_evidence_finding")
        value = _claim_value(claim["field"], _text(claim["value"], 120))
        if value is None:
            raise WorkflowError("invalid_evidence_finding")
        record["claims"].append({"field": claim["field"], "value": value, "artifact_kind": claim["artifact_kind"],
                                 "evidence_ref": claim["evidence_ref"], "origin": claim["origin"],
                                 "status": "unconfirmed"})
    for row in unsupported:
        if isinstance(row, dict) and set(row) == {"field", "reason"} and row["reason"] == "conflicting_claims":
            continue  # recomputed by _finding
        _keys(row, {"field", "artifact_kind", "reason"})
        record = by_kind.get(row["artifact_kind"])
        if record is None or row["reason"] not in _UNSUPPORTED_REASONS:
            raise WorkflowError("invalid_evidence_finding")
        record["unsupported_claims"].append({"field": _text(row["field"], 64), "artifact_kind": row["artifact_kind"],
                                             "reason": row["reason"]})
    return records


def prepare_evidence_finding(packet: dict, manifest_value: dict, package: dict,
                             binding: WorkflowBinding) -> dict:
    """Use an existing worker research packet once its context carries the prepared links.

    The baseline packet checks run unchanged. The package must belong to this
    workflow and scenario and carry at least one link; each link must be
    present, unomitted, in the bounded runtime evidence. The finding is rebuilt
    from validated possession and claim fields, so it is always proposed,
    blocked, unaccepted, without confirmed facts or external authority.
    Supplied status or authorization flags are ignored. No tool or fetch is added.
    """
    baseline = prepare_finding(packet, manifest_value, binding)
    manifest = validate_manifest(manifest_value)
    if not isinstance(package, dict) or package.get("contract") != "household-maintenance-evidence-package/1":
        raise WorkflowError("evidence_package_required")
    finding = package.get("proposed_finding")
    for value in (package, finding):
        if (not isinstance(value, dict) or value.get("synthetic") is not True
                or value.get("workflow_id") != manifest["workflow_id"]
                or value.get("scenario_id") != manifest["scenario_id"]):
            raise WorkflowError("workflow_scope_mismatch")
    if (package.get("baseline_finding_ref") != manifest["finding_ref"]
            or finding.get("responds_to") != manifest["finding_ref"]):
        raise WorkflowError("workflow_scope_mismatch")
    links, already = package.get("item_links"), package.get("already_linked")
    if not isinstance(links, list) or not isinstance(already, list) or not links + already:
        raise WorkflowError("prepared_evidence_missing")
    wanted = []
    for link in links + already:
        if not isinstance(link, dict):
            raise WorkflowError("prepared_evidence_missing")
        if link in links and (link.get("board_id") != binding.board_id or link.get("item_id") != binding.item_id):
            raise WorkflowError("existing_link_scope_mismatch")
        wanted.append({k: link.get(k) for k in ("source_kind", "source_key", "evidence_ref")})
    rows = packet["context"]["evidence"]
    for link in wanted:
        if not any(isinstance(row, dict) and row.get("evidence_ref") == link["evidence_ref"]
                   and row.get("source_kind") == link["source_kind"] and row.get("source_key") == link["source_key"]
                   and row.get("references_omitted") is False for row in rows):
            raise WorkflowError("prepared_evidence_missing")
    result = _finding(manifest, _rebuild_records(finding, wanted))
    result["provenance"] = baseline["provenance"]
    _bounded(result)
    return result


class SyntheticMemoryStore:
    """Offline demo store only. It is not a storage implementation."""

    def __init__(self, board_id: str, store_name: str = "synthetic-evidence-store"):
        self.board_id = _uuid(board_id)
        self.store_name = store_name
        self.objects: dict[str, bytes] = {}

    def put(self, *, sha256: str, media_type: str, data: bytes) -> str:
        reference = f"demo:evidence:sha256:{sha256}"
        self.objects.setdefault(reference, bytes(data))
        return reference

    def read(self, reference: str) -> bytes:
        return self.objects[reference]


def _png_chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def synthetic_fixture(kind: str) -> bytes:
    """Deterministic invented bytes; they depict no real device or record."""
    if kind == "equipment_label_photo":
        rows = b"".join(b"\x00" + bytes((x * 16 + y * 8) % 256 for x in range(16)) for y in range(16))
        stored = b"\x01" + struct.pack("<HH", len(rows), len(rows) ^ 0xFFFF) + rows
        idat = b"\x78\x01" + stored + struct.pack(">I", zlib.adler32(rows))
        return (b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 0, 0, 0, 0))
                + _png_chunk(b"tEXt", b"Comment\x00SYNTHETIC DEMO LABEL. Invented; depicts no real device.")
                + _png_chunk(b"IDAT", idat) + _png_chunk(b"IEND", b""))
    if kind == "service_receipt":
        text = b"BT /F1 10 Tf 20 60 Td (SYNTHETIC DEMO RECEIPT. Invented; not a real record.) Tj ET"
        objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
                   b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                   b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 100] /Contents 4 0 R "
                   b"/Resources << /Font << /F1 5 0 R >> >> >>",
                   b"<< /Length %d >>\nstream\n" % len(text) + text + b"\nendstream",
                   b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
        out, offsets = bytearray(b"%PDF-1.4\n"), []
        for number, body in enumerate(objects, 1):
            offsets.append(len(out))
            out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
        out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
        out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
        return bytes(out)
    raise WorkflowError("unsupported_artifact_kind")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare the synthetic evidence example offline; no storage, database or network.")
    parser.add_argument("command", choices=("demo",))
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--intake", required=True, type=Path)
    parser.add_argument("--output", type=Path, help="New JSON file; existing files are never overwritten")
    args = parser.parse_args(argv)
    try:
        values = []
        for path in (args.manifest, args.intake):
            with path.open("rb") as stream:
                raw = stream.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise WorkflowError("byte_budget_exceeded")
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise WorkflowError("invalid_fields")
            values.append(value)
        manifest, intake = values
        binding = WorkflowBinding(board_id=manifest["demo"]["board_id"], item_id=manifest["demo"]["item_id"],
                                  source_ref=manifest["proposal"]["source_ref"])
        kinds = [a.get("kind") for a in intake.get("artifacts", []) if isinstance(a, dict)]
        result = prepare_evidence(manifest, intake, {k: synthetic_fixture(k) for k in kinds},
                                  binding=binding, store=SyntheticMemoryStore(binding.board_id))
        rendered = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(rendered)
        else:
            print(rendered, end="")
    except (OSError, ValueError, UnicodeError, KeyError, TypeError, AttributeError) as exc:
        code = str(exc) if isinstance(exc, WorkflowError) else "evidence_preparation_failed"
        parser.exit(2, f"{code}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
