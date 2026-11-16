"""Core remains importable without persistence or concrete backend helpers."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
_tmp = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = "sqlite:///" + _tmp.name + "/core.db"

from core.brood import normalize_brood_artifact
from core.types import Artifact, RunStatus
from core import orchestrator
from integrations.brood_credentials import golden_credentials_ref


class CoreBoundaryTests(unittest.TestCase):
    def test_core_import_and_normalization_need_no_persistence(self):
        code = """
import importlib, pkgutil, sys
import core
for module in pkgutil.walk_packages(core.__path__, 'core.'):
    importlib.import_module(module.name)
from core.brood import normalize_brood_artifact
from core.types import Artifact
normalize_brood_artifact(Artifact('vm', 'vm', metadata={'image': 'test', 'ip': '10.0.0.1'}))
for name in ('database', 'golden_images', 'infrastructure_connections', 'secrets_store',
             'service_credentials', 'integrations', 'editor_metadata', 'main'):
    assert name not in sys.modules, name
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            env={**os.environ, "PYTHONPATH": str(ROOT / "api")},
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_explicit_credentials_skip_default_lookup(self):
        lookup = Mock(return_value="default")
        artifact = Artifact(
            "vm", "vm", metadata={"credentials_ref": " EXPLICIT ", "image": "test"}
        )
        result = normalize_brood_artifact(artifact, credentials_resolver=lookup)
        self.assertEqual(result.metadata["access"]["credentials"]["ref"], "explicit")
        lookup.assert_not_called()
        normalize_brood_artifact(result, credentials_resolver=lookup)
        lookup.assert_not_called()

    def test_golden_lookup_keeps_legacy_defaults_and_failure_fallback(self):
        lookup = Mock(return_value={"credentials_ref": " SSH-DEFAULT "})
        with patch.dict(
            sys.modules, {"golden_images": SimpleNamespace(get_profile=lookup)}
        ):
            self.assertEqual(golden_credentials_ref({}), "")
            lookup.assert_not_called()
            self.assertEqual(golden_credentials_ref({"image": " TEST "}), "ssh-default")
            lookup.assert_called_once_with("test")
            lookup.side_effect = RuntimeError("profile unavailable")
            self.assertEqual(golden_credentials_ref({"image": "test"}), "")

    def test_runtime_applies_credentials_before_plugin_import_once(self):
        import run_engine

        order = []
        with (
            patch.object(run_engine, "_initialized", False),
            patch.object(run_engine, "_reconcile_orphaned_runs"),
            patch.object(run_engine, "_wire_triggers"),
            patch(
                "service_credentials.apply_bound_credentials",
                side_effect=lambda: order.append("credentials"),
            ),
            patch.object(
                run_engine,
                "load_plugins",
                side_effect=lambda package: order.append("plugins"),
            ),
        ):
            run_engine.init()
            run_engine.init()
        self.assertEqual(order, ["credentials", "plugins"])


class BroodWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_orchestrator_uses_injected_credential_lookup(self):
        artifact = Artifact("vm", "vm", metadata={"image": "test", "ip": "10.0.0.1"})
        lookup = Mock(return_value="ssh-default")
        result = {"status": RunStatus.SUCCESS, "artifacts": [artifact], "outputs": []}
        with (
            patch.object(
                orchestrator,
                "get_spider",
                return_value=SimpleNamespace(FAMILY="brood", KIND="provision"),
            ),
            patch.object(orchestrator, "run_step", new=AsyncMock(return_value=result)),
            patch.object(orchestrator.events, "emit", new=AsyncMock()),
        ):
            status = await orchestrator.run_scenario(
                "run",
                "test",
                {"steps": [{"id": "vm", "spider": "test", "with": {}}]},
                {},
                Mock(),
                brood_credentials_resolver=lookup,
            )
        self.assertEqual(status, RunStatus.SUCCESS)
        lookup.assert_called_once()
        self.assertEqual(
            artifact.metadata["access"]["credentials"]["ref"], "ssh-default"
        )
