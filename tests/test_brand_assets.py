"""Brand assets must stay independent of icon fonts and remote typefaces."""
from pathlib import Path
import unittest
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "frontend/templates/base.html"
STATIC = ROOT / "frontend/static/img"


class BrandAssetTests(unittest.TestCase):
    def test_svg_assets_are_valid_and_self_contained(self):
        for name in ("favicon.svg", "arachne-wordmark.svg"):
            with self.subTest(name=name):
                svg = ET.parse(STATIC / name).getroot()
                self.assertTrue(svg.attrib.get("viewBox"))
                self.assertTrue(any(node.tag.endswith("path") for node in svg.iter()))

    def test_navigation_uses_wordmark_not_icon_font(self):
        template = BASE.read_text(encoding="utf-8")
        self.assertIn('/static/img/arachne-wordmark.svg?v=2', template)
        self.assertIn('/static/img/favicon.svg?v=1', template)
        self.assertNotIn('<i class="ti ti-spider"></i>', template)

    def test_homepage_sigil_remains_independent(self):
        homepage = (ROOT / "frontend/templates/dashboard.html").read_text(encoding="utf-8")
        self.assertIn('class="arachne-spider"', homepage)


if __name__ == "__main__":
    unittest.main()
