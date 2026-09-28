"""Offline integration tests: connection isolation, lifecycle and optional loading.
Run in an isolated process: PYTHONPATH=api python -m unittest discover -s tests -p test_optional_infrastructure.py
"""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch, AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

_tmp = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = "sqlite:///" + _tmp.name + "/test.db"
from database import Base, engine, SessionLocal, ManagedMachine
import infrastructure_connections as connections
import golden_images
from core.tofu import TofuSpider
from core.types import StepSpec, RunStatus, Artifact
from core.optional_plugins import installed_bundles, module_enabled
from plugins.spiders.tofu_proxmox import TofuProxmoxSpider
from plugins.spiders.tofu_ovirt import TofuOvirtSpider
from managed_machines import register_artifact, destroy_expired_machine
from core.brood import normalize_brood_artifact
import ovirt_api

Base.metadata.create_all(engine)


def token(slug):
    return types.SimpleNamespace(
        kind="basic" if slug.startswith("o") else "token",
        username="bot@internal",
        values={"token": slug + "-secret", "password": slug + "-password"},
    )


class ConnectionsTests(unittest.TestCase):
    def setUp(self):
        with SessionLocal() as db:
            db.query(connections.InfrastructureConnection).delete()
            db.query(ManagedMachine).delete()
            db.commit()

    def save(self, slug, backend="proxmox", **kw):
        with patch.object(connections, "resolve_credential", side_effect=token):
            connections.save_connection(
                slug=slug,
                label=slug,
                backend=backend,
                endpoint=f"https://{slug}.example/api",
                credential_slug=slug,
                **kw,
            )

    def test_per_process_credentials_and_immutable_endpoint(self):
        self.save("p1")
        self.save("p2")
        self.save("o1", "ovirt")
        before = dict(os.environ)
        with patch.object(connections, "resolve_credential", side_effect=token):
            a = connections.execution_env("p1", "proxmox")
            b = connections.execution_env("p2", "proxmox")
            c = connections.execution_env("o1", "ovirt")
            self.assertNotEqual(a["PROXMOX_VE_API_TOKEN"], b["PROXMOX_VE_API_TOKEN"])
            self.assertEqual(c["TF_VAR_ovirt_password"], "o1-password")
            with self.assertRaisesRegex(ValueError, "immutable"):
                connections.save_connection(
                    slug="p1",
                    label="p1",
                    backend="proxmox",
                    endpoint="https://other",
                    credential_slug="p1",
                )
        self.assertEqual(before, dict(os.environ))
        self.assertNotIn("p1-secret", json.dumps(connections.list_connections()))

    def test_disabled_connection_still_allows_cleanup(self):
        self.save("p1", enabled=False)
        with self.assertRaisesRegex(ValueError, "disabled"):
            connections.get_connection("p1", "proxmox")
        with patch.object(connections, "resolve_credential", side_effect=token):
            self.assertIn(
                "PROXMOX_VE_API_TOKEN", connections.execution_env("p1", "proxmox")
            )

    def test_same_vm_id_and_name_on_different_connections(self):
        for c in ["p1", "p2"]:
            artifact = Artifact(
                name="same",
                type="vm",
                location="101",
                metadata={
                    "vm_id": "101",
                    "connection": c,
                    "backend": "tofu-proxmox",
                    "os": "redos8",
                    "ip": "10.0.0.2",
                },
            )
            register_artifact("run", None, normalize_brood_artifact(artifact))
        with SessionLocal() as db:
            self.assertEqual(db.query(ManagedMachine).count(), 2)
        register_artifact(
            "run",
            None,
            Artifact(
                name="same",
                type="vm",
                location="same",
                metadata={
                    "connection": "p1",
                    "backend": "tofu-proxmox",
                    "state": "destroyed",
                },
            ),
        )
        with SessionLocal() as db:
            self.assertEqual(
                db.query(ManagedMachine).filter_by(state="destroyed").count(), 1
            )
            active = db.query(ManagedMachine).filter_by(state="running").one()
            self.assertEqual(active.backend_metadata["connection"], "p2")

    def test_optional_modules_are_not_imported_by_default(self):
        with patch.dict(os.environ, {"ARACHNE_PLUGINS": ""}):
            self.assertEqual(installed_bundles(), set())
            self.assertFalse(module_enabled("plugins.spiders.tofu_ovirt"))
            self.assertFalse(module_enabled("plugins.spiders.ansible_local"))
            self.assertTrue(module_enabled("plugins.spiders.forgejo"))
        with patch.dict(os.environ, {"ARACHNE_PLUGINS": "tofu-ovirt"}):
            self.assertTrue(module_enabled("plugins.spiders.tofu_ovirt"))
            self.assertFalse(module_enabled("plugins.spiders.tofu_proxmox"))

    def test_backend_and_connection_mismatch_rejected(self):
        profile = {
            "backend": "ovirt",
            "connection": "o1",
            "os": "redos8",
            "template_id": "a",
        }
        with patch("plugins.spiders.tofu_ovirt.get_profile", return_value=profile):
            with self.assertRaisesRegex(ValueError, "another connection"):
                TofuOvirtSpider().dispatch(
                    StepSpec(
                        "vm",
                        "tofu-ovirt",
                        "brood",
                        with_={"name": "vm", "connection": "o2"},
                    ),
                    {},
                )
        with patch("plugins.spiders.tofu_proxmox.get_profile", return_value=profile):
            with self.assertRaisesRegex(ValueError, "another backend"):
                TofuProxmoxSpider().dispatch(
                    StepSpec("vm", "tofu-proxmox", "brood", with_={"name": "vm"}), {}
                )

    def test_state_isolation_and_legacy_location(self):
        with patch.dict(os.environ, {"TOFU_STATE_ROOT": _tmp.name}):
            p, o = TofuProxmoxSpider(), TofuOvirtSpider()
            self.assertEqual(p._state_dir("vm"), Path(_tmp.name) / "vm")
            self.assertNotEqual(p._state_dir("vm", "one"), p._state_dir("vm", "two"))
            self.assertNotEqual(p._state_dir("vm", "one"), o._state_dir("vm", "one"))
            with self.assertRaises(ValueError):
                p._state_dir("vm", "../escape")

    def test_ipv4_selection_rejects_ambiguous_networks(self):
        data = {
            "reported_device": [
                {
                    "name": "eth0",
                    "ips": {"ip": [{"address": "fe80::1"}, {"address": "10.81.1.2"}]},
                },
                {"name": "docker0", "ips": {"ip": [{"address": "172.17.0.1"}]}},
                {"name": "lo", "ips": {"ip": [{"address": "127.0.0.1"}]}},
            ]
        }
        import contextlib

        with (
            patch.object(
                ovirt_api, "_client", side_effect=lambda _: contextlib.nullcontext(None)
            ),
            patch.object(ovirt_api, "_get", return_value=data),
        ):
            vm = "11111111-1111-1111-1111-111111111111"
            self.assertEqual(
                ovirt_api.primary_ipv4(vm, "o1", cidr="10.81.0.0/16"), "10.81.1.2"
            )
            self.assertEqual(
                ovirt_api.primary_ipv4(vm, "o1", interface="eth0"), "10.81.1.2"
            )
            self.assertEqual(ovirt_api.primary_ipv4(vm, "o1", interface="missing"), "")
            with self.assertRaisesRegex(ValueError, "Several"):
                ovirt_api.primary_ipv4(vm, "o1")


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_destroy_uses_saved_inputs_and_module_without_profile(self):
        with (
            tempfile.TemporaryDirectory() as root,
            patch.dict(os.environ, {"TOFU_STATE_ROOT": root}),
        ):
            spider = TofuOvirtSpider()
            with (
                patch("plugins.spiders.tofu_ovirt.get_connection"),
                patch(
                    "plugins.spiders.tofu_ovirt.get_profile",
                    side_effect=AssertionError("no lookup"),
                ),
            ):
                handle = spider.dispatch(
                    StepSpec(
                        "vm",
                        "tofu-ovirt",
                        "destroy",
                        with_={"name": "vm", "connection": "o1"},
                    ),
                    {},
                )
            state_dir = spider._state_dir("vm", "o1")
            (state_dir / "module").mkdir(parents=True)
            (state_dir / "module/main.tf").write_text("original module")
            (state_dir / "terraform.tfstate").write_text("{}")
            (state_dir / "arachne-inputs.json").write_text(
                json.dumps({"vars": ["-var=template_id=old"]})
            )
            calls = []

            async def run(cmd, **kwargs):
                calls.append(cmd)
                if False:
                    yield

            with (
                patch.object(spider, "_run_cmd", side_effect=run),
                patch("core.tofu.shutil.which", return_value="/tofu"),
                patch.object(connections, "execution_env", return_value={}),
            ):
                _ = [line async for line in spider.stream_logs(handle)]
            self.assertEqual(spider.get_status(handle), RunStatus.SUCCESS)
            self.assertIn("-var=template_id=old", calls[-1])
            self.assertEqual(
                (state_dir / "module/main.tf").read_text(), "original module"
            )
            self.assertFalse((state_dir / "terraform.tfstate").exists())

    async def test_existing_state_is_not_overwritten(self):
        with (
            tempfile.TemporaryDirectory() as root,
            patch.dict(os.environ, {"TOFU_STATE_ROOT": root}),
        ):
            spider = TofuOvirtSpider()
            backend = {
                "connection": "o1",
                "image": "img",
                "os": "redos8",
                "template": {"cpu": 1, "memory_bytes": 1024},
                "cluster_id": "cl",
                "template_vm_id": "tpl",
            }
            with patch.object(spider, "_resolve_backend", return_value=backend):
                h = spider.dispatch(
                    StepSpec("vm", "tofu-ovirt", "brood", with_={"name": "vm"}), {}
                )
            d = spider._state_dir("vm", "o1")
            (d / "module").mkdir(parents=True)
            (d / "terraform.tfstate").write_text("{}")
            (d / "module/main.tf").write_text("original")
            with patch("core.tofu.shutil.which", return_value="/tofu"):
                logs = [l.text async for l in spider.stream_logs(h)]
            self.assertEqual((d / "module/main.tf").read_text(), "original")
            self.assertEqual(spider.get_status(h), RunStatus.FAILED)
            self.assertTrue(any("already exists" in l for l in logs))

    async def test_reaper_routes_ovirt_and_connection(self):
        claimed = {
            "id": 123,
            "name": "vm",
            "os": "redos8",
            "backend": "tofu-ovirt",
            "backend_metadata": {"connection": "o1"},
        }
        run = AsyncMock(return_value={"status": RunStatus.SUCCESS})
        with (
            patch("managed_machines._claim", return_value=claimed),
            patch("managed_machines.get_spider", return_value=TofuOvirtSpider()),
            patch("managed_machines.run_step", run),
            patch("managed_machines._mark_destroyed") as done,
        ):
            await destroy_expired_machine(123)
            self.assertEqual(run.call_args.args[2], "tofu-ovirt")
            self.assertEqual(run.call_args.args[3]["with_"]["connection"], "o1")
            done.assert_called_once_with(123)

    async def test_failed_apply_preserves_partial_vm_for_cleanup(self):
        with (
            tempfile.TemporaryDirectory() as root,
            patch.dict(os.environ, {"TOFU_STATE_ROOT": root}),
        ):
            spider = TofuOvirtSpider()
            backend = {
                "connection": "o1",
                "image": "img",
                "os": "redos8",
                "template": {"cpu": 1, "memory_bytes": 1024},
                "cluster_id": "cl",
                "template_vm_id": "tpl",
            }
            with patch.object(spider, "_resolve_backend", return_value=backend):
                h = spider.dispatch(
                    StepSpec("vm", "tofu-ovirt", "brood", with_={"name": "vm"}), {}
                )

            async def run(cmd, **kwargs):
                if cmd[1] == "apply":
                    (spider._state_dir("vm", "o1") / "terraform.tfstate").write_text(
                        json.dumps(
                            {
                                "resources": [
                                    {
                                        "type": "ovirt_vm",
                                        "instances": [
                                            {"attributes": {"id": "created-vm"}}
                                        ],
                                    }
                                ]
                            }
                        )
                    )
                    raise RuntimeError("start failed")
                if False:
                    yield

            with (
                patch.object(spider, "_run_cmd", side_effect=run),
                patch("core.tofu.shutil.which", return_value="/tofu"),
                patch.object(connections, "execution_env", return_value={}),
            ):
                _ = [line async for line in spider.stream_logs(h)]
            self.assertEqual(spider.get_status(h), RunStatus.FAILED)
            self.assertEqual(spider.get_artifacts(h)[0].location, "created-vm")
            self.assertEqual(spider.get_artifacts(h)[0].metadata["connection"], "o1")


if __name__ == "__main__":
    unittest.main()
