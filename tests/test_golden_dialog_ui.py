"""Golden Image modal markup regression checks."""
from pathlib import Path
import unittest

from jinja2 import Environment

TEMPLATE = Path(__file__).resolve().parents[1] / "frontend/templates/admin/golden_images.html"


class GoldenDialogUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = TEMPLATE.read_text(encoding="utf-8")

    def test_jinja_syntax(self):
        Environment().parse(self.html)

    def test_os_combobox_has_explicit_popup(self):
        for fragment in (
            'id="golden-os-combobox"',
            'id="golden-os"',
            'id="golden-os-options"',
            'role="combobox"',
            'role="listbox"',
            'class="golden-os-toggle"',
            "onclick=\"toggleGoldenOsOptions()\"",
            'oninput="filterGoldenOsOptions(true)"',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.html)
        self.assertNotIn('<datalist', self.html)

    def test_enabled_checkbox_has_matching_visual_box(self):
        self.assertIn('id="golden-enabled" type="checkbox"', self.html)
        self.assertIn('<span class="check-control-box" aria-hidden="true"></span>', self.html)
        self.assertIn('class="golden-enabled-label"', self.html)

    def test_helper_text_is_outside_input_label(self):
        self.assertIn('<p class="golden-help golden-os-hint">', self.html)
        self.assertNotIn('.golden-dialog label > span', self.html)


if __name__ == "__main__":
    unittest.main()
