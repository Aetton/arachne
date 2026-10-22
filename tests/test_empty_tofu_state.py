"""Empty-state retries must never erase state or allow unknown/resource states."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from core.tofu_state import ensure_provisionable_state


class StateTests(unittest.TestCase):
    def test_absent_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "terraform.tfstate"
            ensure_provisionable_state(path)
            self.assertFalse(path.exists())

    def test_empty_state_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "terraform.tfstate"
            raw = json.dumps(dict(version=4, serial=12, lineage="original",
                                  resources=[], outputs={"old": {"value": "stale"}}))
            path.write_text(raw)
            ensure_provisionable_state(path)
            self.assertEqual(path.read_text(), raw)

    def test_invalid_and_nonempty_states_are_preserved(self):
        samples = ["", "{", "null", "[]", "{}", '{"version": 3, "resources": []}',
                   '{"version": 4}', '{"version": 4, "resources": null}']
        for mode, instances in [("managed", [{"attributes": {"id": "101"}}]),
                                ("managed", []), ("data", [])]:
            samples.append(json.dumps(dict(version=4, resources=[
                dict(mode=mode, type="vm", instances=instances)])))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "terraform.tfstate"
            for raw in samples:
                with self.subTest(raw=raw):
                    path.write_text(raw)
                    with self.assertRaises(ValueError):
                        ensure_provisionable_state(path)
                    self.assertEqual(path.read_text(), raw)


if __name__ == "__main__":
    unittest.main()
