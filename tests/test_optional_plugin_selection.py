"""Selection and image-pruning tests without application dependencies."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
from core.optional_plugins import BUNDLES, installed_bundles, resolve_bundles


class SelectionTests(unittest.TestCase):
    def test_selection(self):
        self.assertEqual(resolve_bundles(""), set())
        self.assertEqual(resolve_bundles(" tofu-ovirt, tofu-ovirt "), {"tofu-ovirt"})
        self.assertEqual(resolve_bundles(" all, tofu-ovirt "), set(BUNDLES))
        with self.assertRaisesRegex(ValueError, "typo"):
            resolve_bundles("all,typo")

    def test_all_includes_future_registry_entries(self):
        with patch.dict(BUNDLES, {"future": "plugins.spiders.future"}):
            self.assertIn("future", resolve_bundles("all"))

    def test_all_cannot_enable_pruned_modules(self):
        with patch.dict(os.environ, ARACHNE_PLUGINS="all"):
            with patch("core.optional_plugins.Path.exists", return_value=True):
                with patch("core.optional_plugins.Path.read_text", return_value='["tofu-ovirt"]'):
                    with self.assertRaisesRegex(ValueError, "rebuild"):
                        installed_bundles()

    def test_build_selection_and_pruning(self):
        for selection in ("all", "tofu-ovirt", ""):
            with self.subTest(selection=selection), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                shutil.copytree(ROOT / "api", root / "api")
                shutil.copytree(ROOT / "scripts", root / "scripts")
                shutil.copytree(ROOT / "tofu", root / "tofu")
                env = dict(os.environ, ARACHNE_PLUGINS=selection, PYTHONPATH=str(root / "api"))
                resolver = root / "arachne-optional-plugins.py"
                shutil.copyfile(root / "api/core/optional_plugins.py", resolver)
                cli = subprocess.check_output(
                    [sys.executable, str(resolver)],
                    env=env, text=True,
                ).strip()
                expected = resolve_bundles(selection)
                self.assertEqual(set(filter(None, cli.split(","))), expected)
                subprocess.run([sys.executable, str(root / "scripts/select-plugin-bundles.py")],
                               env=env, check=True)
                self.assertEqual(set(json.loads((root / "installed-bundles.json").read_text())), expected)
                for name, module in BUNDLES.items():
                    self.assertEqual((root / "api" / (module.replace(".", "/") + ".py")).exists(),
                                     name in expected)


if __name__ == "__main__":
    unittest.main()
