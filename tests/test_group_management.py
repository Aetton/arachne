"""Run in an isolated process: DB, HTTP routes, ACL tree and YAML regression."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

_tmp = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = "sqlite:///" + _tmp.name + "/groups.db"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from fastapi.testclient import TestClient
from database import Base, engine, SessionLocal, Component, Scenario, ScenarioVersion, ScenarioACL, User
from auth.security import create_token
from group_tree import validate_parents, build_tree
import main
import scenario_store
import yaml

Base.metadata.create_all(engine)


class GroupTests(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        self.db = SessionLocal()
        self.db.add(User(username="admin", password_hash="unused", roles=["admin"], teams=[], is_active=True))
        for slug, parent in [("root", None), ("child", "root"), ("leaf", "child"), ("other", None)]:
            self.db.add(Component(slug=slug, label=slug.title(), parent_group=parent))
            self.db.flush()
        for slug in ("a", "b", "c"):
            version = scenario_store.save_draft(self.db, slug, dict(
                label=slug.upper(), component="leaf", steps=[dict(id="step", spider="demo", action="run")]), None)
            scenario = self.db.query(Scenario).filter_by(slug=slug).one()
            scenario_store.publish(self.db, scenario, version)
        self.db.commit()
        self.client = TestClient(main.app)
        self.client.cookies.set("arachne_session", create_token("admin"))

    def tearDown(self):
        self.client.close()
        self.db.close()

    def post(self, payload):
        return self.client.post("/admin/scenarios/layout", json=payload)

    def test_cycle_unknown_and_delete_nonempty(self):
        for parent in ("leaf", "missing", "root"):
            response = self.post(dict(kind="group", slug="root", parent_group=parent))
            self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.client.post("/admin/components/root/delete").status_code, 409)
        self.db.expire_all()
        self.assertIsNone(self.db.get(Component, "root").parent_group)

    def test_move_and_reorder_persist(self):
        self.assertEqual(self.post(dict(kind="group", slug="child", parent_group="other")).status_code, 200)
        self.assertEqual(self.post(dict(kind="scenario", slug="c", before="a")).status_code, 200)
        self.db.expire_all()
        self.assertEqual(self.db.get(Component, "child").parent_group, "other")
        self.assertEqual([s.slug for s in self.db.query(Scenario).order_by(Scenario.sort_order)], ["c","a","b"])
        exported = yaml.safe_load(scenario_store.export_yaml(self.db))
        self.assertEqual(exported["components"]["child"]["parent_group"], "other")
        self.assertEqual(exported["scenarios"]["c"]["sort_order"], 0)

    def test_dashboard_nested_acl_and_admin_render(self):
        with patch("access.can_access_scenario", side_effect=lambda db, user, s, permission: s.slug == "b"):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('data-scenario="b"', response.text)
        self.assertNotIn('data-scenario="a"', response.text)
        for group in ("root", "child", "leaf"):
            self.assertIn(f'data-component="{group}"', response.text)
        self.assertNotIn('data-component="other"', response.text)
        response = self.client.get("/admin/scenarios")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('id="manager-search"', response.text)

    def test_group_sibling_order_and_invalid_target(self):
        self.assertEqual(self.post(dict(kind="group", slug="other", parent_group=None, before="root")).status_code, 200)
        self.db.expire_all()
        roots = self.db.query(Component).filter(Component.parent_group.is_(None)).order_by(Component.sort_order).all()
        self.assertEqual([r.slug for r in roots], ["other", "root"])
        self.assertEqual(self.post(dict(kind="group", slug="root", parent_group="leaf", before="missing")).status_code, 400)
        self.assertEqual(self.post(dict(kind="scenario", slug="a", before="missing")).status_code, 400)

    def test_move_scenario_updates_definition_and_preserves_history_acl(self):
        scenario = self.db.query(Scenario).filter_by(slug="a").one()
        old_id = scenario.current_version_id
        old_definition = dict(self.db.get(ScenarioVersion, old_id).definition)
        scenario.enabled = False
        scenario_store.replace_acl(self.db, scenario.id, [dict(subject_type="role", subject_key="developer", permission="view", effect="allow", match_mode="all")])
        result = self.post(dict(kind="move_scenario", slug="a", group="other"))
        self.assertEqual(result.status_code, 200, result.text)
        self.db.expire_all()
        self.assertEqual(scenario.component, "other")
        self.assertFalse(scenario.enabled)
        self.assertNotEqual(scenario.current_version_id, old_id)
        self.assertEqual(self.db.get(ScenarioVersion, old_id).definition, old_definition)
        self.assertEqual(scenario_store.published_definition(self.db, scenario)["component"], "other")
        self.assertEqual(self.db.query(ScenarioACL).filter_by(scenario_id=scenario.id).count(), 1)
        version_id = scenario.current_version_id
        self.assertEqual(self.post(dict(kind="move_scenario", slug="a", group="missing")).status_code, 400)
        self.assertEqual(self.post(dict(kind="move_scenario", slug="a", group="other")).status_code, 200)
        self.db.expire_all()
        self.assertEqual(scenario.current_version_id, version_id)

    def test_move_draft_stays_draft_and_appends(self):
        definition = dict(label="Draft", component="root", steps=[dict(id="step", spider="demo", action="run")])
        old = scenario_store.save_draft(self.db, "draft", definition, None)
        old_id = old.id
        result = self.post(dict(kind="move_scenario", slug="draft", group="leaf"))
        self.assertEqual(result.status_code, 200, result.text)
        self.db.expire_all()
        scenario = self.db.query(Scenario).filter_by(slug="draft").one()
        self.assertIsNone(scenario.current_version_id)
        self.assertEqual(scenario.component, "leaf")
        self.assertEqual(scenario.sort_order, 1)
        latest = self.db.query(ScenarioVersion).filter_by(scenario_id=scenario.id).order_by(ScenarioVersion.version.desc()).first()
        self.assertEqual(latest.definition["component"], "leaf")
        self.assertEqual(latest.status, "draft")
        self.assertEqual(self.db.get(ScenarioVersion, old_id).definition["component"], "root")

    def test_authorization(self):
        self.client.cookies.clear()
        self.assertEqual(self.post(dict(kind="group", slug="child", parent_group=None)).status_code, 401)

    def test_new_group_defaults_to_root(self):
        result = self.client.post("/admin/components", data={"slug":"new","label":"New"}, follow_redirects=False)
        self.assertEqual(result.status_code, 303, result.text)
        self.db.expire_all()
        self.assertIsNone(self.db.get(Component,"new").parent_group)

    def test_bootstrap_child_before_parent(self):
        path = Path(_tmp.name) / "import.yaml"
        path.write_text(yaml.safe_dump({"components":{
            "new-child":{"label":"Child","parent_group":"new-parent"},
            "new-parent":{"label":"Parent"}}, "scenarios":{}}, sort_keys=False))
        with patch.dict(os.environ, SCENARIOS_CONFIG=str(path)):
            scenario_store.bootstrap_from_yaml(self.db)
        self.assertEqual(self.db.get(Component, "new-child").parent_group, "new-parent")


if __name__ == "__main__":
    unittest.main()
