"""HTTP regression tests; run in an isolated process with SQLite."""

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
import sys
from unittest.mock import AsyncMock, patch
from unittest.mock import AsyncMock, patch
from fastapi.responses import HTMLResponse

_tmp = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = "sqlite:///" + _tmp.name + "/journal.db"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from database import Base, engine, SessionLocal, User, Component, Scenario, Run
from auth.security import create_token
from fastapi.testclient import TestClient
import main
from fastapi.responses import HTMLResponse


class JournalTests(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        self.db = SessionLocal()
        for name, roles in [("admin", ["admin"]), ("alice", []), ("bob", [])]:
            self.db.add(
                User(
                    username=name,
                    password_hash="unused",
                    roles=roles,
                    teams=[],
                    is_active=True,
                )
            )
        self.db.flush()
        self.ids = {u.username: u.id for u in self.db.query(User)}
        for slug, parent in [
            ("root", None),
            ("child", "root"),
            ("leaf", "child"),
            ("other", None),
        ]:
            self.db.add(Component(slug=slug, label=slug.title(), parent_group=parent))
            self.db.flush()
        self.db.add(Scenario(slug="demo", label="Current demo", component="other"))
        for number, actor, group in [
            (1, "alice", "root"),
            (2, "alice", "leaf"),
            (3, "bob", "other"),
        ]:
            self.db.add(
                Run(
                    id=f"run-{number}",
                    user_id=self.ids[actor],
                    scenario="demo",
                    scenario_snapshot={
                        "label": f"Historical {number}",
                        "component": group,
                    },
                    status="success",
                    created_at=datetime(2026, 1, number),
                )
            )
        self.db.add(
            Run(id="legacy", user_id=self.ids["bob"], scenario="demo", status="failed")
        )
        self.db.commit()
        self.client = TestClient(main.app)
        self.login("admin")

    def login(self, name):
        self.client.cookies.set("arachne_session", create_token(name))

    def tearDown(self):
        self.client.close()
        self.db.close()

    def journal(self, **params):
        response = self.client.get("/journal", params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.text

    def test_actor_and_sort(self):
        html = self.journal(actor=self.ids["alice"], sort="created", direction="asc")
        self.assertIn("/journal/run-1", html)
        self.assertIn("/journal/run-2", html)
        self.assertNotIn("/journal/run-3", html)
        self.assertLess(html.index("/journal/run-1"), html.index("/journal/run-2"))
        self.assertNotIn("/journal/run-", self.journal(actor="invalid"))

    def test_restart_preserves_typed_parameters_and_uses_current_actor(self):
        run = self.db.get(Run, "run-1")
        params = {"branch": "feature/demo", "publish": False, "count": 0,
                  "optional": "", "targets": ["a", "b"]}
        run.params = params
        self.db.commit()
        with patch.object(main.config_loader, "get_scenario", return_value={"label": "Demo"}), \
             patch.object(main.run_engine, "start_run_async", new_callable=AsyncMock, return_value="new-run") as start, \
             patch.object(main, "_render_run", return_value=HTMLResponse("new view")):
            response = self.client.post("/runs/run-1/restart")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "new view")
        self.assertEqual(response.headers["HX-Trigger"], "runStarted")
        start.assert_awaited_once_with(self.ids["admin"], "demo", params)
        self.db.refresh(run)
        self.assertEqual(run.params, params)

    def test_restart_checks_run_and_current_scenario_access(self):
        self.login("alice")
        with patch.object(main.run_engine, "start_run_async", new_callable=AsyncMock) as start:
            self.assertEqual(self.client.post("/runs/run-3/restart").status_code, 403)
            self.assertEqual(self.client.post("/runs/run-1/restart").status_code, 403)
            self.assertEqual(self.client.post("/runs/missing/restart").status_code, 404)
            start.assert_not_awaited()

    def test_restart_unpublished_scenario_does_not_start(self):
        with patch.object(main.config_loader, "get_scenario", return_value=None), \
             patch.object(main.run_engine, "start_run_async", new_callable=AsyncMock) as start:
            self.assertEqual(self.client.post("/runs/run-1/restart").status_code, 404)
            start.assert_not_awaited()

    def test_restart_preserves_parameters_and_uses_current_actor(self):
        original = self.db.get(Run, "run-1")
        params = {"branch": "feature/demo", "publish": False, "count": 0, "empty": ""}
        original.params = params
        self.db.commit()
        for status in ("success", "failed", "cancelled", "running"):
            original.status = status
            self.db.commit()
            with patch.object(main.config_loader, "get_scenario", return_value={"label": "Demo"}), \
                 patch.object(main.run_engine, "start_run_async", new_callable=AsyncMock, return_value="new-run") as start, \
                 patch.object(main, "_render_run", return_value=HTMLResponse("new run")):
                response = self.client.post("/runs/run-1/restart")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["HX-Trigger"], "runStarted")
                start.assert_awaited_once_with(self.ids["admin"], "demo", params)
        self.db.refresh(original)
        self.assertEqual(original.params, params)

    def test_run_view_has_restart_action(self):
        response = self.client.get("/runs/run-1/view")
        self.assertEqual(response.status_code, 200)
        self.assertIn('hx-post="/runs/run-1/restart"', response.text)
        self.assertIn('hx-disabled-elt="this"', response.text)

    def test_nested_groups_and_snapshot(self):
        html = self.journal(group="root")
        self.assertIn("/journal/run-1", html)
        self.assertIn("/journal/run-2", html)
        self.assertNotIn("/journal/run-3", html)
        self.assertNotIn("/journal/legacy", html)
        self.assertIn("Root / Child / Leaf", html)
        html = self.journal(group="root", descendants="false")
        self.assertIn("/journal/run-1", html)
        self.assertNotIn("/journal/run-2", html)
        self.assertIn("/journal/legacy", self.journal(group="other"))

    def test_pagination_search_and_status(self):
        html = self.journal(page_size=1, sort="created", direction="asc")
        self.assertIn("/journal/run-1", html)
        self.assertNotIn("/journal/run-2", html)
        self.assertIn("page=2", html)
        self.assertIn("/journal/run-2", self.journal(q="Historical 2"))
        self.assertNotIn("/journal/run-", self.journal(q="%"))
        self.assertIn("/journal/legacy", self.journal(status="failed"))
        self.assertNotIn("/journal/run-", self.journal(scenario="missing"))
        self.assertEqual(self.client.get("/journal?page_size=101").status_code, 422)

    def test_access_and_no_filter_leak(self):
        self.login("alice")
        html = self.journal()
        self.assertNotIn("/journal/run-3", html)
        self.assertNotIn(">bob", html)
        self.assertNotIn('value="other"', html)
        self.assertNotIn("/journal/run-3", self.journal(actor=self.ids["bob"]))
        self.assertEqual(self.client.get("/journal/run-3").status_code, 403)
        self.assertEqual(self.client.get("/journal/run-1").status_code, 200)
        self.assertEqual(self.client.get("/journal/missing").status_code, 404)
        self.client.cookies.clear()
        self.assertEqual(self.client.get("/journal").status_code, 401)


if __name__ == "__main__":
    unittest.main()
