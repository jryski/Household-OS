"""Synthetic-only compiler and existing worker callback seam checks."""
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from household_os.maintenance_workflow import (
    MAX_BYTES, WorkflowBinding, WorkflowError, compile_workflow, make_researcher,
    prepare_finding, validate_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/maintenance/furnace-baseline"


class MaintenanceWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((EXAMPLE / "manifest.json").read_text())
        self.package = compile_workflow(self.manifest)
        self.binding = WorkflowBinding(
            board_id=self.manifest["demo"]["board_id"],
            item_id=self.manifest["demo"]["item_id"],
            source_ref=self.manifest["proposal"]["source_ref"],
        )

    def packet(self):
        context = deepcopy(self.package["preview"])
        context.update(contract="life-runtime-context/1", scope={"board_id": self.binding.board_id},
                       coverage={"evidence_omitted": 0, "dependencies_omitted": 0, "activity_omitted": 0})
        context["item"].update(state="researching", version=3)
        return {"authority": "research_only", "contentTrust": "untrusted",
                "item_version": 3, "context_id": "synthetic-context-3", "context": context}

    def test_frozen_ui_fixture_is_reproducible_and_bounded(self):
        self.assertEqual(self.package, json.loads((EXAMPLE / "prepared.json").read_text()))
        for value in (self.package, self.package["worker_context"], self.package["proposed_finding"]):
            self.assertLessEqual(len(json.dumps(value, ensure_ascii=False).encode()), MAX_BYTES)
        self.assertTrue(self.package["synthetic"])
        self.assertFalse(self.package["proposal"]["dispatched"])
        self.assertEqual(self.package["preview"]["item"]["state"], "proposed")
        self.assertFalse(self.package["proposed_finding"]["accepted"])

    def test_proposal_arguments_match_existing_rpc_and_links(self):
        migration = (ROOT / "supabase/migrations/20261016111304_life_assistance_work_plane.sql").read_text()
        signature = re.search(r"create function public.life_propose_work_v1\((.*?)\) returns uuid", migration, re.S).group(1)
        names = set(re.findall(r"\bp_[a-z_]+(?=\s)", signature))
        self.assertEqual(set(self.package["proposal"]["arguments"]), names)
        self.assertEqual(self.package["proposal"]["operation"], "life_propose_work_v1")
        self.assertEqual(set(self.package["item_links"][0]),
                         {"board_id", "item_id", "relation", "source_store", "source_kind",
                          "source_key", "evidence_ref", "observed_at"})
        self.assertNotIn("p_item_id", self.package["proposal"]["arguments"])

    def test_missing_information_never_becomes_due_or_known(self):
        self.assertEqual(self.package["worker_context"]["observations"],
                         {"model": None, "last_service_at": None, "service_status": "unknown"})
        self.assertIsNone(self.package["proposal"]["arguments"]["p_due_at"])
        self.assertIsNone(self.package["proposal"]["arguments"]["p_not_before"])
        self.assertTrue(self.package["proposed_finding"]["blocked"])
        self.assertEqual(self.package["proposed_finding"]["requested_evidence"], self.manifest["requested_evidence"])
        self.assertEqual(self.package["proposed_finding"]["observations"], self.package["worker_context"]["observations"])

    def test_manifest_cannot_supply_dispatch_or_live_authority(self):
        for change in (lambda m: m.update(synthetic=False),
                       lambda m: m.update(rpc="arbitrary_rpc"),
                       lambda m: m["proposal"].update(due_at="2030-01-01T00:00:00Z"),
                       lambda m: m["observations"].update(model="Invented-model"),
                       lambda m: m["observations"].update(service_status="overdue"),
                       lambda m: m["demo"].update(item_id="11111111-1111-4111-8111-111111111111")):
            manifest = deepcopy(self.manifest)
            change(manifest)
            with self.assertRaises(WorkflowError):
                validate_manifest(manifest)

    def test_utf8_budget_and_unknown_fields_fail_closed(self):
        manifest = deepcopy(self.manifest)
        manifest["proposal"]["description"] = "é" * MAX_BYTES
        with self.assertRaisesRegex(WorkflowError, "byte_budget_exceeded"):
            compile_workflow(manifest)
        manifest = deepcopy(self.manifest)
        manifest["proposal"]["leaseToken"] = "synthetic"
        with self.assertRaisesRegex(WorkflowError, "invalid_fields"):
            compile_workflow(manifest)

    def test_existing_worker_research_packet_produces_review_artifact(self):
        packet = self.packet()
        packet["context"]["item"]["lease_token"] = "not-copied-to-finding"
        artifact = prepare_finding(packet, self.manifest, self.binding)
        self.assertEqual(artifact["provenance"]["item_version"], 3)
        self.assertEqual(artifact["provenance"]["context_id"], packet["context_id"])
        self.assertFalse(artifact["accepted"])
        self.assertFalse(artifact["external_action_authorized"])
        self.assertNotIn("lease_token", json.dumps(artifact))

    def test_wrong_binding_version_or_incomplete_context_is_rejected_before_storage(self):
        changes = (
            lambda p: p.update(authority="execute"),
            lambda p: p["context"]["scope"].update(board_id="wrong-board"),
            lambda p: p["context"]["item"].update(id="wrong-item"),
            lambda p: p["context"]["item"].update(state="proposed"),
            lambda p: p.update(item_version=2),
            lambda p: p["context"]["item"].update(description_truncated=True),
            lambda p: p["context"]["coverage"].update(evidence_omitted=1),
            lambda p: p["context"].update(evidence=[]),
            lambda p: p["context"]["item"].update(description="Changed proposal"),
        )
        writes = []
        researcher = make_researcher(self.manifest, binding=self.binding,
                                    persist_finding=lambda value: writes.append(value),
                                    finding_factory=lambda **kwargs: kwargs)
        for change in changes:
            packet = self.packet()
            change(packet)
            with self.assertRaises(WorkflowError):
                researcher(packet)
        self.assertEqual(writes, [])

    def test_host_supplied_artifact_writer_and_finding_type_feed_worker_callback(self):
        @dataclass
        class Finding:
            reference: str
            blocked: bool

        class Worker:
            def research(self, callback):
                return callback(self.packet)

        stored = []

        def persist(artifact):
            stored.append(artifact)
            return "demo:stored:furnace-finding:attempt-1"

        worker = Worker()
        worker.packet = self.packet()
        callback = make_researcher(self.manifest, binding=self.binding,
                                   persist_finding=persist, finding_factory=Finding)
        result = worker.research(callback)
        self.assertIsInstance(result, Finding)
        self.assertEqual(result.reference, "demo:stored:furnace-finding:attempt-1")
        self.assertTrue(result.blocked)
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["status"], "proposed")

    def test_cli_prepares_only_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "prepared.json"
            command = [sys.executable, "-m", "household_os.maintenance_workflow", "prepare",
                       "--manifest", str(EXAMPLE / "manifest.json"), "--output", str(output)]
            first = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            original = output.read_bytes()
            self.assertEqual(json.loads(original), self.package)
            second = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(second.returncode, 2)
            self.assertEqual(output.read_bytes(), original)
            self.assertEqual(second.stderr, "workflow_preparation_failed\n")


if __name__ == "__main__":
    unittest.main()
