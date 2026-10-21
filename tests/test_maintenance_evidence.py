"""Synthetic-only evidence intake checks for the furnace maintenance workflow."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from household_os.maintenance_evidence import (
    MAX_ARTIFACT_BYTES, SyntheticMemoryStore, prepare_evidence, prepare_evidence_finding,
    sha256_hex, synthetic_fixture,
)
from household_os.maintenance_workflow import WorkflowBinding, WorkflowError, compile_workflow

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "examples/maintenance/furnace-baseline"
EXAMPLE = ROOT / "examples/maintenance/furnace-evidence"


class EvidenceIntakeTests(unittest.TestCase):
    def setUp(self):
        self.baseline_bytes = {name: (BASELINE / name).read_bytes() for name in ("manifest.json", "prepared.json")}
        self.manifest = json.loads(self.baseline_bytes["manifest.json"])
        self.intake = json.loads((EXAMPLE / "intake.json").read_text())
        self.binding = WorkflowBinding(board_id=self.manifest["demo"]["board_id"],
                                       item_id=self.manifest["demo"]["item_id"],
                                       source_ref=self.manifest["proposal"]["source_ref"])
        self.store = SyntheticMemoryStore(self.binding.board_id)
        self.artifacts = {k: synthetic_fixture(k) for k in ("equipment_label_photo", "service_receipt")}

    def prepare(self, intake=None, artifacts=None, store=None, existing=()):
        return prepare_evidence(self.manifest, self.intake if intake is None else intake,
                                self.artifacts if artifacts is None else artifacts,
                                binding=self.binding, store=store or self.store, existing_links=existing)

    def without(self, kind):
        intake = deepcopy(self.intake)
        intake["artifacts"] = [a for a in intake["artifacts"] if a["kind"] != kind]
        return intake, {k: v for k, v in self.artifacts.items() if k != kind}

    def test_frozen_example_is_reproducible_and_baseline_untouched(self):
        package = self.prepare()
        self.assertEqual(package, json.loads((EXAMPLE / "prepared.json").read_text()))
        for name, raw in self.baseline_bytes.items():
            self.assertEqual((BASELINE / name).read_bytes(), raw)
        self.assertEqual(compile_workflow(self.manifest), json.loads(self.baseline_bytes["prepared.json"]))
        self.assertTrue(package["baseline_unchanged"])

    def test_references_are_digest_verified_and_use_existing_shapes(self):
        package = self.prepare()
        for row, kind in zip(package["ingest_sources"], self.artifacts):
            digest = sha256_hex(self.artifacts[kind])
            self.assertEqual(row["source_sha256"], digest)
            self.assertEqual(sha256_hex(self.store.read(row["source_ref"])), digest)
            self.assertEqual(set(row), {"source_kind", "source_ref", "source_sha256", "source_label",
                                        "observed_at", "document_date", "parser_agent", "parser_version",
                                        "parse_status", "confidence", "metadata"})
            self.assertIsNone(row["document_date"])
            self.assertEqual(row["parse_status"], "needs_review")
        migration = (ROOT / "supabase/migrations/20261016111304_life_assistance_work_plane.sql").read_text()
        for link in package["item_links"]:
            self.assertEqual(set(link), {"board_id", "item_id", "relation", "source_store", "source_kind",
                                         "source_key", "evidence_ref", "observed_at"})
            self.assertEqual(link["relation"], "evidence")
            self.assertIn("'evidence'", migration)

    def test_claims_stay_proposals_and_unsupported_fields_stay_unknown(self):
        finding = self.prepare()["proposed_finding"]
        self.assertEqual(finding["status"], "proposed")
        self.assertFalse(finding["accepted"])
        self.assertFalse(finding["external_action_authorized"])
        self.assertTrue(finding["blocked"])
        self.assertEqual(finding["confirmed_facts"], {})
        self.assertEqual(finding["proposed_observations"]["service_status"], "unknown")
        self.assertTrue(all(c["status"] == "unconfirmed" for c in finding["claims"]))
        self.assertIn({"artifact_kind": "service_receipt", "field": "model",
                       "reason": "field_not_supported_by_artifact"}, finding["unsupported_claims"])
        self.assertEqual(finding["responds_to"], self.manifest["finding_ref"])
        self.assertNotEqual(finding["reference"], self.manifest["finding_ref"])

    def test_label_photo_does_not_establish_service_date(self):
        intake = deepcopy(self.intake)
        intake["artifacts"][0]["claims"].append({"field": "last_service_at", "value": "2029-01-01",
                                                 "origin": "automated_extraction"})
        intake["artifacts"][1]["claims"] = []
        finding = self.prepare(intake)["proposed_finding"]
        self.assertIsNone(finding["proposed_observations"]["last_service_at"])
        self.assertIn("last_service_at unknown", finding["still_missing"])

    def test_non_date_and_conflicting_claims_stay_unknown(self):
        intake = deepcopy(self.intake)
        intake["artifacts"][1]["claims"] = [{"field": "last_service_at", "value": "last autumn",
                                             "origin": "person_transcription"}]
        finding = self.prepare(intake)["proposed_finding"]
        self.assertIsNone(finding["proposed_observations"]["last_service_at"])
        self.assertIn("value_not_a_calendar_date", json.dumps(finding["unsupported_claims"]))
        intake = deepcopy(self.intake)
        intake["artifacts"][0]["claims"].append({"field": "model", "value": "DEMO-FURNACE-200",
                                                 "origin": "automated_extraction"})
        finding = self.prepare(intake)["proposed_finding"]
        self.assertIsNone(finding["proposed_observations"]["model"])
        self.assertIn({"field": "model", "reason": "conflicting_claims"}, finding["unsupported_claims"])

    def test_either_or_both_artifacts_may_be_absent(self):
        for kind in self.artifacts:
            intake, artifacts = self.without(kind)
            finding = self.prepare(intake, artifacts)["proposed_finding"]
            self.assertTrue(finding["blocked"])
            self.assertEqual(len(finding["possession"]), 1)
            self.assertTrue(any("not supplied" in m for m in finding["still_missing"]))
        intake = deepcopy(self.intake)
        intake["artifacts"] = []
        package = self.prepare(intake, {})
        self.assertEqual(package["item_links"], [])
        self.assertEqual(package["proposed_finding"]["proposed_observations"],
                         {"model": None, "last_service_at": None, "service_status": "unknown"})
        self.assertTrue(package["proposed_finding"]["reference"].endswith(":evidence:none"))

    def test_repeat_intake_does_not_duplicate(self):
        first = self.prepare()
        later = deepcopy(self.intake)
        later["received_at"] = "2030-01-17T09:00:00Z"
        second = self.prepare(later, existing=first["item_links"])
        self.assertEqual(second["item_links"], [])
        self.assertEqual(len(second["already_linked"]), 2)
        self.assertEqual(len(self.store.objects), 2)
        self.assertEqual(second["proposed_finding"]["reference"], first["proposed_finding"]["reference"])

    def test_store_reference_change_for_same_bytes_is_refused(self):
        first = self.prepare()
        existing = deepcopy(first["item_links"])
        existing[0]["evidence_ref"] = "demo:evidence:other"
        with self.assertRaisesRegex(WorkflowError, "store_reference_conflict"):
            self.prepare(existing=existing)

    def test_digest_mismatch_and_tampered_store_are_refused(self):
        artifacts = dict(self.artifacts)
        artifacts["service_receipt"] = artifacts["service_receipt"] + b"\n"
        with self.assertRaisesRegex(WorkflowError, "digest_mismatch"):
            self.prepare(artifacts=artifacts)

        class Tampering(SyntheticMemoryStore):
            def read(self, reference):
                return super().read(reference) + b"x"
        with self.assertRaisesRegex(WorkflowError, "stored_digest_mismatch"):
            self.prepare(store=Tampering(self.binding.board_id))

    def test_wrong_scope_is_refused(self):
        with self.assertRaisesRegex(WorkflowError, "store_scope_mismatch"):
            self.prepare(store=SyntheticMemoryStore("00000000-0000-4000-8000-000000000999"))
        intake = deepcopy(self.intake)
        intake["scenario_id"] = "other-demo"
        with self.assertRaisesRegex(WorkflowError, "workflow_scope_mismatch"):
            self.prepare(intake)
        other = dict(self.prepare()["item_links"][0], item_id="00000000-0000-4000-8000-000000000998")
        with self.assertRaisesRegex(WorkflowError, "existing_link_scope_mismatch"):
            self.prepare(existing=[other])

    def test_caller_cannot_supply_path_url_or_storage_authority(self):
        for extra in ({"path": "/tmp/receipt.pdf"}, {"url": "https://example.invalid/x"}, {"bucket": "demo"}):
            intake = deepcopy(self.intake)
            intake["artifacts"][0].update(extra)
            with self.assertRaisesRegex(WorkflowError, "invalid_fields"):
                self.prepare(intake)

        class UrlStore(SyntheticMemoryStore):
            def put(self, **kwargs):
                return "https://example.invalid/signed?token=demo"
        with self.assertRaisesRegex(WorkflowError, "opaque_store_reference_required"):
            self.prepare(store=UrlStore(self.binding.board_id))

    def test_type_and_size_bounds(self):
        intake = deepcopy(self.intake)
        intake["artifacts"][0]["media_type"] = "application/pdf"
        with self.assertRaisesRegex(WorkflowError, "unsupported_media_type"):
            self.prepare(intake)
        intake = deepcopy(self.intake)
        intake["artifacts"][1]["media_type"] = "image/png"
        with self.assertRaisesRegex(WorkflowError, "media_type_mismatch"):
            self.prepare(intake)
        big = b"\x89PNG\r\n\x1a\n" + b"\x00" * MAX_ARTIFACT_BYTES
        intake = deepcopy(self.intake)
        intake["artifacts"][0]["declared_sha256"] = sha256_hex(big)
        with self.assertRaisesRegex(WorkflowError, "artifact_size_out_of_bounds"):
            self.prepare(intake, dict(self.artifacts, equipment_label_photo=big))
        intake = deepcopy(self.intake)
        intake["artifacts"][0]["kind"] = "nameplate_scan"
        with self.assertRaisesRegex(WorkflowError, "unsupported_artifact_kind"):
            self.prepare(intake)
        intake = deepcopy(self.intake)
        intake["synthetic"] = False
        with self.assertRaisesRegex(WorkflowError, "synthetic_intake_required"):
            self.prepare(intake)
        with self.assertRaisesRegex(WorkflowError, "artifact_set_mismatch"):
            self.prepare(artifacts={"equipment_label_photo": self.artifacts["equipment_label_photo"]})

    def test_existing_worker_packet_carries_prepared_references(self):
        package = self.prepare()
        preview = deepcopy(compile_workflow(self.manifest)["preview"])
        preview.update(contract="life-runtime-context/1", scope={"board_id": self.binding.board_id},
                       coverage={"evidence_omitted": 0, "dependencies_omitted": 0, "activity_omitted": 0})
        preview["item"].update(state="researching", version=4)
        packet = {"authority": "research_only", "contentTrust": "untrusted", "item_version": 4,
                  "context_id": "synthetic-context-4", "context": preview}
        with self.assertRaisesRegex(WorkflowError, "prepared_evidence_missing"):
            prepare_evidence_finding(deepcopy(packet), self.manifest, package, self.binding)
        for link in package["item_links"]:
            preview["evidence"].append({k: v for k, v in link.items() if k not in {"board_id", "item_id"}}
                                       | {"references_omitted": False})
        finding = prepare_evidence_finding(packet, self.manifest, package, self.binding)
        self.assertEqual(finding["provenance"]["item_version"], 4)
        self.assertFalse(finding["accepted"])
        packet["authority"] = "execute"
        with self.assertRaises(WorkflowError):
            prepare_evidence_finding(packet, self.manifest, package, self.binding)

    def test_cli_demo_prepares_only_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "prepared.json"
            command = [sys.executable, "-m", "household_os.maintenance_evidence", "demo",
                       "--manifest", str(BASELINE / "manifest.json"), "--intake", str(EXAMPLE / "intake.json"),
                       "--output", str(output)]
            first = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(output.read_bytes(), (EXAMPLE / "prepared.json").read_bytes())
            second = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(second.returncode, 2)
            self.assertEqual(second.stderr, "evidence_preparation_failed\n")


if __name__ == "__main__":
    unittest.main()
