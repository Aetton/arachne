"""HTTP registration must not depend on execution plugin startup."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
_tmp = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = "sqlite:///" + _tmp.name + "/routes.db"


class RouteRegistrationTests(unittest.TestCase):
    def test_routes_are_present_before_runtime_init(self):
        import main
        import run_engine

        self.assertFalse(run_engine._initialized)
        routes = list(main.app.openapi()["paths"])
        for path in (
            "/admin/settings",
            "/admin/infrastructure",
            "/admin/golden-images",
            "/admin/ansible",
            "/admin/secrets",
            "/api/admin/scenario-dsl",
            "/runs/{run_id}/artifacts/{artifact_index}/console",
        ):
            self.assertEqual(routes.count(path), 1, path)

    def test_router_import_does_not_import_main(self):
        code = """
import importlib
import sys
for name in ('ansible_settings_admin', 'editor_metadata', 'golden_images_admin',
             'infrastructure_admin', 'secrets_admin', 'settings_admin', 'vm_console'):
    importlib.import_module('routes.' + name)
assert 'main' not in sys.modules
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            env={**os.environ, "PYTHONPATH": str(ROOT / "api")},
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_plugin_discovery_does_not_import_http(self):
        code = """
import sys
from unittest.mock import patch
from core.registry import load_plugins, all_spiders
with patch('service_credentials.apply_bound_credentials'):
    load_plugins()
assert 'forgejo' in all_spiders()
assert 'main' not in sys.modules
assert not any(name.startswith('routes.') for name in sys.modules)
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            env={**os.environ, "PYTHONPATH": str(ROOT / "api"), "ARACHNE_PLUGINS": ""},
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
