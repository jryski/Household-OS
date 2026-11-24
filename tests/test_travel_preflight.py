"""Preflight through the CLI; no production providers or private config."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class TravelPreflightTest(unittest.TestCase):
    def test_invalid_scheduled_tick_cannot_create_state_or_emit_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.sqlite"
            env = {k: v for k, v in os.environ.items() if not k.startswith("HOUSE_")}
            env["HOUSE_TRAVEL_NOTIFY_URL"] = "https://fixture-user:fixture-sensitive@example.test"
            env["HOUSE_SUPABASE_SERVICE_ROLE_KEY"] = "fixture-sensitive"
            completed = subprocess.run(
                [sys.executable, "-m", "household_os.travel_cli", "tick",
                 "--live", "--scheduled", "--db", str(state)],
                env=env, capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 1, completed.stderr)
            self.assertFalse(state.exists())
            self.assertNotIn("fixture-sensitive", completed.stdout + completed.stderr)
            result = json.loads(completed.stdout)
            self.assertFalse(result["configuration_ready"])
            self.assertFalse(result["live_verified"])
            self.assertFalse(result["capabilities"]["notifications"])
            self.assertTrue(result["capabilities"]["state_path"])
