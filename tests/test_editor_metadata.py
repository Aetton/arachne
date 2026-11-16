"""One installed-plugin catalog for API and initial editor HTML."""

import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
_tmp = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = "sqlite:///" + _tmp.name + "/editor.db"

from bs4 import BeautifulSoup
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from auth.deps import get_current_user
from core.editor_metadata import SPIDER_CONTRACTS, scenario_dsl_metadata
from routes.editor_metadata import router
import main


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.spiders = {
            "forgejo": SimpleNamespace(FAMILY="weave", KIND="build"),
            "ansible-local": SimpleNamespace(FAMILY="command", KIND="build"),
            "tofu-proxmox": SimpleNamespace(FAMILY="brood", KIND="provision"),
            "tofu-ovirt": SimpleNamespace(FAMILY="brood", KIND="provision"),
            "custom": SimpleNamespace(FAMILY="command", KIND="build"),
        }
        self.profiles = [
            dict(slug="pve", backend="proxmox", enabled=True),
            dict(slug="ovirt", backend="ovirt", enabled=True),
            dict(slug="disabled", backend="proxmox", enabled=False),
        ]
        self.patchers = [
            patch("core.editor_metadata.all_spiders", return_value=self.spiders),
            patch(
                "core.editor_metadata.all_triggers", return_value={"manual": object()}
            ),
        ]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)

    def test_installed_catalog_and_custom_plugin_fallback(self):
        catalog = scenario_dsl_metadata()
        spiders = {s["name"]: s for s in catalog["spiders"]}
        self.assertEqual(set(spiders), set(self.spiders))
        self.assertEqual(spiders["forgejo"]["actions"], ["weave"])
        self.assertIn("playbook_ref", spiders["ansible-local"]["inputs"])
        self.assertEqual(spiders["custom"]["actions"], ["command"])
        self.assertEqual(spiders["custom"]["kind"], "build")
        self.assertEqual(catalog["triggers"], ["manual"])
        self.assertTrue(catalog["docs_url"].startswith("/wiki/docs/ru/"))

    def test_profiles_and_returned_contracts_are_isolated(self):
        first = scenario_dsl_metadata(self.profiles)
        spiders = {s["name"]: s for s in first["spiders"]}
        self.assertEqual(spiders["tofu-proxmox"]["inputs"]["image"]["options"], ["pve"])
        self.assertEqual(spiders["tofu-ovirt"]["inputs"]["image"]["options"], ["ovirt"])
        spiders["forgejo"]["inputs"]["repo"]["description"] = "changed"
        again = {s["name"]: s for s in scenario_dsl_metadata()["spiders"]}
        self.assertNotEqual(
            again["forgejo"]["inputs"]["repo"]["description"], "changed"
        )
        self.assertNotIn("options", SPIDER_CONTRACTS["tofu-proxmox"]["inputs"]["image"])

    def test_api_matches_safe_initial_html_and_requires_admin(self):
        app = FastAPI()
        app.include_router(router)
        user = SimpleNamespace(id=1, username="admin", roles=["admin"], teams=[])
        app.dependency_overrides[get_current_user] = lambda: user
        with (
            patch("routes.editor_metadata.list_profiles", return_value=self.profiles),
            patch("main.list_profiles", return_value=self.profiles),
        ):
            expected = scenario_dsl_metadata(self.profiles)
            # Include HTML metacharacters to verify the JSON script cannot be escaped.
            expected["spiders"][0]["description"] = "</script><script>alert(1)</script>"
            with patch("main.scenario_dsl_metadata", return_value=expected):
                db = Mock()
                db.query.return_value.order_by.return_value.all.return_value = []
                response = main.admin_scenario_new(
                    Request(
                        {
                            "type": "http",
                            "method": "GET",
                            "path": "/admin/scenarios/new",
                            "scheme": "http",
                            "server": ("test", 80),
                            "headers": [],
                        }
                    ),
                    user=user,
                    db=db,
                )
            html = BeautifulSoup(response.body, "html.parser")
            initial = json.loads(html.find(id="scenario-dsl-metadata").string)
            self.assertEqual(initial, expected)
            self.assertNotIn("<script>alert(1)</script>", response.body.decode())
            # The real catalog returned by both paths is identical.
            expected["spiders"][0]["description"] = scenario_dsl_metadata(
                self.profiles
            )["spiders"][0]["description"]
            with TestClient(app) as client:
                self.assertEqual(client.get("/api/admin/scenario-dsl").json(), expected)
                user.roles = ["developer"]
                self.assertEqual(client.get("/api/admin/scenario-dsl").status_code, 403)
