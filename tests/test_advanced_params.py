"""Run in an isolated process: advanced input rendering and submission."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

_tmp = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = "sqlite:///" + _tmp.name + "/advanced.db"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
from bs4 import BeautifulSoup
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader
from database import Base, engine, SessionLocal, User, Component, Scenario
from auth.security import create_token
import main
import scenario_store


def definition(params):
    return dict(
        label="Build",
        component="builds",
        params=params,
        steps=[dict(id="build", spider="demo", action="run")],
    )


def param(name, **kwargs):
    return dict(name=name, label=name, type="string", default="value", **kwargs)


class AdvancedParamsTests(unittest.TestCase):
    def render(self, params):
        env = Environment(
            loader=FileSystemLoader(ROOT / "frontend/templates"), autoescape=True
        )
        return BeautifulSoup(
            env.get_template("scenario_form.html").render(
                s=definition(params), key="build"
            ),
            "html.parser",
        )

    def test_legacy_and_basic_have_no_disclosure(self):
        for params in [[], [param("legacy")], [param("explicit", group="basic")]]:
            page = self.render(params)
            self.assertIsNone(page.select_one("[data-advanced-params]"))
            self.assertEqual(len(page.select("input[name]")), len(params))

    def test_partition_preserves_order_and_values(self):
        page = self.render(
            [
                param("a", group="advanced"),
                param("b"),
                dict(
                    name="flag",
                    label="Flag",
                    type="boolean",
                    default=True,
                    group="advanced",
                ),
                dict(
                    name="choice",
                    label="Choice",
                    type="choice",
                    options=["x", "y"],
                    default="y",
                    group="advanced",
                ),
                param("c", group="basic"),
            ]
        )
        section = page.select_one("[data-advanced-params]")
        self.assertFalse(section.has_attr("open"))
        self.assertEqual(
            [p["name"] for p in section.select("[name]")], ["a", "flag", "choice"]
        )
        self.assertEqual(
            [p["name"] for p in page.select("form > .thread-fields [name]")], ["b", "c"]
        )
        self.assertTrue(section.select_one("[name=flag]").has_attr("checked"))
        self.assertEqual(section.select_one("option[selected]")["value"], "y")
        self.assertFalse(section.select("[disabled]"))
        self.assertEqual(len(page.select("form")), 1)

    def test_required_and_source_error(self):
        page = self.render([param("required", required=True, group="advanced")])
        self.assertTrue(page.select_one("[name=required]").has_attr("required"))
        page = self.render(
            [
                dict(
                    name="branch",
                    label="Branch",
                    type="select",
                    group="advanced",
                    source=dict(type="git_branches"),
                    source_error="Network error",
                    options=[],
                )
            ]
        )
        self.assertTrue(page.select_one("[data-advanced-params]").has_attr("open"))
        self.assertIn("Network error", page.get_text())

    def test_group_validation(self):
        for value in ["basic", "advanced"]:
            scenario_store.validate_definition(definition([param("p", group=value)]))
        for value in ["advnaced", None, [], {}]:
            with self.assertRaisesRegex(ValueError, "param group"):
                scenario_store.validate_definition(
                    definition([param("p", group=value)])
                )

    def test_store_export_and_submission(self):
        import yaml

        Base.metadata.create_all(engine)
        with SessionLocal() as db:
            user = User(
                username="admin",
                password_hash="unused",
                roles=["admin"],
                teams=[],
                is_active=True,
            )
            db.add_all([user, Component(slug="builds", label="Builds")])
            db.commit()
            data = definition(
                [
                    param("version"),
                    param("flags", group="advanced"),
                    dict(
                        name="debug",
                        label="Debug",
                        type="boolean",
                        default=True,
                        group="advanced",
                    ),
                ]
            )
            version = scenario_store.save_draft(db, "build", data, user.id)
            scenario_store.publish(
                db, db.query(Scenario).filter_by(slug="build").one(), version
            )
            exported = yaml.safe_load(scenario_store.export_yaml(db))
            self.assertEqual(exported["scenarios"]["build"]["params"], data["params"])
            uid = user.id
        client = TestClient(main.app, raise_server_exceptions=True)
        try:
            client.cookies.set("arachne_session", create_token("admin"))
            with (
                patch.object(main.config_loader, "get_scenario", return_value=data),
                patch.object(main.access, "can_access_scenario", return_value=True),
                patch.object(
                    main.run_engine,
                    "start_run_async",
                    new_callable=AsyncMock,
                    return_value="run-id",
                ) as start,
                patch.object(main, "_render_run", return_value=HTMLResponse("ok")),
            ):
                response = client.post(
                    "/scenarios/build/run",
                    data={"version": "1.2", "flags": "-race", "debug": "true"},
                )
                self.assertEqual(response.status_code, 200)
                start.assert_awaited_once_with(
                    uid, "build", {"version": "1.2", "flags": "-race", "debug": True}
                )
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
