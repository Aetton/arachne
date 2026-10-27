"""Isolated HTTP and runtime regressions for large logs."""

import asyncio
import json
import unittest
from unittest.mock import patch, AsyncMock
from sqlalchemy import event
import test_run_journal as fixtures
import main
import run_engine
from database import Run, User, engine


class RunPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.JournalTests()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()
        for key in ("buffer-test",):
            run_engine._done[key] = True
            run_engine._release_runtime(key)

    def test_history_does_not_load_logs_or_resolve_inputs(self):
        statements = []

        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", capture)
        try:
            with patch.object(
                main.config_loader,
                "get_scenario",
                side_effect=AssertionError("dynamic lookup"),
            ):
                response = self.fixture.client.get("/runs/history")
            self.assertEqual(response.status_code, 200)
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        run_queries = [s for s in statements if "FROM runs" in s]
        self.assertTrue(run_queries)
        for sql in run_queries:
            self.assertNotIn("runs.log", sql)
            self.assertNotIn("runs.artifacts", sql)
            self.assertNotIn("runs.scenario_snapshot", sql)

    def test_metadata_response_omits_log_rows(self):
        db = self.fixture.db
        run = db.get(Run, "run-1")
        run.log = json.dumps(
            [
                dict(step_id="build", seq=i, stream="stdout", text="unique-log-payload")
                for i in range(100)
            ]
        )
        db.commit()
        full = self.fixture.client.get("/runs/run-1/view")
        metadata = self.fixture.client.get("/runs/run-1/view?metadata_only=true")
        self.assertEqual(metadata.status_code, 200)
        self.assertIn("unique-log-payload", full.text)
        self.assertNotIn("unique-log-payload", metadata.text)
        self.assertIn("step-title", metadata.text)
        self.assertLess(len(metadata.content), len(full.content))

    def test_cache_eviction_keeps_active_and_stream_tail(self):
        rid = "buffer-test"
        run_engine._init_runtime(rid)
        records = run_engine.live_records(rid)
        records.append(dict(text="last line"))
        run_engine._release_runtime(rid)
        self.assertTrue(run_engine.has_runtime(rid))
        run_engine._done[rid] = True
        run_engine._release_runtime(rid)
        self.assertFalse(run_engine.has_runtime(rid))
        self.assertEqual(records, [dict(text="last line")])
        for cache in (
            run_engine._live,
            run_engine._outputs,
            run_engine._status,
            run_engine._artifact_output_indexes,
        ):
            self.assertNotIn(rid, cache)

    def test_evicted_child_results_remain_available_from_database(self):
        run = self.fixture.db.get(Run, "run-1")
        run.log = json.dumps([dict(text="child output")])
        run.artifacts = [dict(name="package")]
        self.fixture.db.commit()
        self.assertFalse(run_engine.has_runtime("run-1"))
        self.assertTrue(run_engine.is_done("run-1"))
        self.assertEqual(run_engine.get_status("run-1"), run_engine.RunStatus.SUCCESS)
        self.assertEqual(run_engine.live_records("run-1"), [dict(text="child output")])
        self.assertEqual(run_engine.live_outputs("run-1"), [dict(name="package")])

    def test_cleanup_scheduled_only_after_successful_persistence(self):
        async def check(failure):
            rid = "buffer-test"
            run_engine._init_runtime(rid)
            loop = asyncio.get_running_loop()
            with (
                patch.object(
                    run_engine.orchestrator,
                    "run_scenario",
                    new=AsyncMock(return_value=run_engine.RunStatus.SUCCESS),
                ),
                patch.object(
                    run_engine.asyncio, "to_thread", new=AsyncMock(side_effect=failure)
                ),
                patch.object(loop, "call_later") as schedule,
            ):
                await run_engine._execute(rid, "demo", {}, {})
                if failure:
                    schedule.assert_not_called()
                    self.assertTrue(run_engine.has_runtime(rid))
                else:
                    schedule.assert_called_once_with(
                        60, run_engine._release_runtime, rid
                    )

        asyncio.run(check(None))
        asyncio.run(check(RuntimeError("database unavailable")))

    def test_subscriber_finishes_after_cache_eviction(self):
        rid = "run-1"
        run_engine._init_runtime(rid)
        records = run_engine.live_records(rid)
        records.extend([dict(text="first"), dict(text="last")])

        async def collect():
            user = self.fixture.db.query(User).filter_by(username="admin").one()
            response = await main.run_stream(rid, user, self.fixture.db)
            run_engine._done[rid] = True
            run_engine._release_runtime(rid)
            return [item async for item in response.body_iterator]

        result = asyncio.run(collect())
        self.assertEqual(
            result, ["data: first\n\n", "data: last\n\n", "event: done\ndata: end\n\n"]
        )


if __name__ == "__main__":
    unittest.main()
