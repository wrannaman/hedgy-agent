"""An exit-zero greeting must not pass as a completed scheduled scan."""

import json
import os
import subprocess
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

from strategies.csp_401k.verify_run import verify_run


class VerifyRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.here = self.root / "strategies/csp_401k"
        self.started = time.time() - 1
        self.now = datetime.now()
        self.day = self.now.date().isoformat()
        self.scan = self.here / "state/last_scan.json"
        self.screen = self.here / "state/last_screen.json"
        self.decision = self.root / "state/agent_decision.json"
        self.log = self.here / "logs" / f"{self.day}.jsonl"

    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data) + "\n")

    def complete(self):
        for path in (self.scan, self.screen):
            self.write(path, {"timestamp": self.now.isoformat()})
        self.write(self.decision, {
            "date": self.day, "new_trades": [], "hunt_reason": "No candidates cleared."
        })
        self.write(self.log, {
            "timestamp": self.now.isoformat(), "scan_type": "daily_scan"
        })

    def test_complete_no_trade_day_is_success(self):
        self.complete()
        verify_run(self.started, self.here)

    def test_empty_turn_is_failure(self):
        with self.assertRaises(ValueError):
            verify_run(self.started, self.here)

    def test_earlier_same_day_outputs_cannot_hide_empty_turn(self):
        self.complete()
        os.utime(self.screen, (self.started - 60, self.started - 60))
        with self.assertRaisesRegex(ValueError, "last_screen.*not written"):
            verify_run(self.started, self.here)

    def test_touching_old_data_does_not_make_it_fresh(self):
        self.complete()
        self.write(self.scan, {"timestamp": datetime.fromtimestamp(self.started - 60).isoformat()})
        with self.assertRaisesRegex(ValueError, "stale data"):
            verify_run(self.started, self.here)

    def test_partial_or_invalid_decision_fails(self):
        self.complete()
        for data in ([1], {"date": self.day}, {"date": "2000-01-01"}):
            with self.subTest(data=data):
                self.write(self.decision, data)
                with self.assertRaises(ValueError):
                    verify_run(self.started, self.here)

    def test_no_action_log_alone_is_not_a_scan(self):
        self.complete()
        self.write(self.log, {"timestamp": self.now.isoformat(), "type": "NO_ACTION"})
        with self.assertRaisesRegex(ValueError, "no daily_scan"):
            verify_run(self.started, self.here)

    def test_runner_retries_exit_zero_without_outputs(self):
        # Exercise the actual shell function and retry loop with a harmless agent.
        source = (Path(__file__).resolve().parents[1] / "run_daily.sh").read_text()
        block = source.split("  run_claude_once() {", 1)[1].split("  # ---- Guard 2:", 1)[0]
        block = "run_claude_once() {" + block
        fake = self.root / "fake-claude"
        fake.write_text("#!/bin/bash\necho 'Ready. What do you need?'\n")
        fake.chmod(0o755)
        block = block.replace('"${CLAUDE_BIN:-claude}"', str(fake))
        verifier = Path(__file__).resolve().parents[1] / "verify_run.py"
        (self.root / "verify_run.py").write_text(verifier.read_text())
        harness = """
set -u
DAY=2026-09-17
REPO_ROOT="$PWD"
CLAUDE_MODEL=test
CLAUDE_TIMEOUT=20
CLAUDE_MAX_ATTEMPTS=2
CLAUDE_RETRY_BACKOFF=0
CLAUDE_AUTH_OK=1
MODE=intraday
kill_tree() { kill "$1"; }
""" + block + '\n[ "$RC" -ne 0 ] && [ "$ATTEMPT" -eq 2 ]\n'
        result = subprocess.run(["bash", "-c", harness], cwd=self.root,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count("Ready. What do you need?"), 2)
        self.assertIn("exhausted 2 attempts", result.stdout)


if __name__ == "__main__":
    unittest.main()


def test_scheduler_defaults_to_opus_55():
    source = (Path(__file__).resolve().parents[1] / "run_daily.sh").read_text()
    assert 'CLAUDE_MODEL="${CLAUDE_MODEL:-claude-opus-5-5}"' in source
