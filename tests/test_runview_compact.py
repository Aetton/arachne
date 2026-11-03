"""Regression tests: metadata-only run views must not retain log payloads."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import runview


class CompactRunViewTests(unittest.TestCase):
    def test_task_structure_and_failure_survive_without_lines(self):
        records = [
            {"step_id": "install", "stream": "system", "text": "━━━ step 'install' via ansible ━━━"},
            {"step_id": "install", "stream": "stdout", "text": "TASK [Prepare]"},
            {"step_id": "install", "stream": "stdout", "text": "secret-value-long-log-line"},
            {"step_id": "install", "stream": "stdout", "text": "TASK [Install]"},
            {"step_id": "install", "stream": "stderr", "text": "fatal: failure"},
        ]
        full = runview.build(records, "failed")
        compact = runview.build(records, "failed", include_lines=False)
        self.assertEqual([x["id"] for x in compact], ["install"])
        self.assertEqual(compact[0]["spider"], "ansible")
        self.assertEqual(compact[0]["status"], "failed")
        self.assertEqual([x["title"] for x in compact[0]["tasks"]],
                         ["Prepare", "Install"])
        self.assertEqual(compact[0]["tasks"][1]["status"], "failed")
        self.assertTrue(any(task["lines"] for task in full[0]["tasks"]))
        self.assertTrue(all(not task["lines"] for task in compact[0]["tasks"]))

    def test_large_log_does_not_accumulate_lines_in_compact_mode(self):
        records = [{"step_id": "build", "stream": "system",
                    "text": "━━━ step 'build' via forgejo ━━━"},
                   {"step_id": "build", "stream": "stdout", "text": "TASK [Build]"}]
        records.extend({"step_id": "build", "stream": "stdout",
                        "text": "log payload " + str(i)} for i in range(50000))
        compact = runview.build(records, "running", include_lines=False)
        self.assertEqual(len(compact), 1)
        self.assertEqual(compact[0]["status"], "running")
        self.assertEqual(len(compact[0]["tasks"]), 1)
        self.assertEqual(compact[0]["tasks"][0]["lines"], [])

    def test_legacy_full_mode_keeps_lines(self):
        records = [{"step_id": "s", "stream": "stdout", "text": "hello"}]
        self.assertEqual(runview.build(records, "success")[0]["tasks"][0]["lines"],
                         ["hello"])


if __name__ == "__main__":
    unittest.main()
