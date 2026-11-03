"""Restart control and editable settings HTML contract checks."""
from pathlib import Path
import unittest
from jinja2 import Environment

TEMPLATE = Path(__file__).resolve().parents[1] / "frontend/templates/admin/settings.html"


class SettingsUIContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = TEMPLATE.read_text(encoding="utf-8")

    def test_jinja_parses(self):
        Environment().parse(self.html)

    def test_restart_control_is_guarded(self):
        self.assertIn('id="settings-restart-button"', self.html)
        self.assertIn("if not restart_available", self.html)
        self.assertIn("restartArachne()", self.html)
        self.assertIn("/admin/settings/restart", self.html)

    def test_restart_inputs_have_set_and_reset_actions(self):
        self.assertIn("if s.editable", self.html)
        self.assertIn("s.input_kind == 'bool'", self.html)
        self.assertIn("s.input_kind == 'bus'", self.html)
        self.assertIn('/admin/settings/set', self.html)
        self.assertIn('/admin/settings/reset', self.html)


if __name__ == "__main__":
    unittest.main()
