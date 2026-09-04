from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from core import thread_adapter  # noqa: E402
import run_engine  # noqa: E402


class ThreadCancelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        for entry in list(thread_adapter._active.values()):
            task = entry.get("task")
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        thread_adapter._active.clear()

    async def test_cancel_handler_cancels_step_with_handle(self):
        task = asyncio.create_task(asyncio.sleep(60))
        thread_adapter._active["run-1:step-1"] = {
            "task": task,
            "spider": object(),
            "handle": object(),
            "cancel_requested": False,
        }

        result = await thread_adapter._cancel_handler({
            "run_id": "run-1",
            "step_id": "step-1",
        })

        self.assertEqual(result, {"accepted": True})
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_cancel_handler_defers_cancel_during_dispatch(self):
        task = asyncio.create_task(asyncio.sleep(60))
        entry = {
            "task": task,
            "spider": object(),
            "handle": None,
            "cancel_requested": False,
        }
        thread_adapter._active["run-1:step-1"] = entry

        result = await thread_adapter._cancel_handler({
            "run_id": "run-1",
            "step_id": "step-1",
        })

        self.assertEqual(result, {"accepted": True, "reason": "dispatching"})
        self.assertTrue(entry["cancel_requested"])
        self.assertFalse(task.done())

    async def test_execute_honors_deferred_cancel_after_dispatch(self):
        handle = SimpleNamespace(metadata={})
        spider = SimpleNamespace(
            dispatch=Mock(return_value=handle),
            cancel=Mock(return_value=True),
        )
        step = SimpleNamespace(id="step-1", spider="fake")
        logs = []

        async def emit_log(text, stream, seq, step_id):
            logs.append((text, stream, seq, step_id))

        current_task = asyncio.current_task()
        thread_adapter._active["run-1:step-1"] = {
            "task": current_task,
            "spider": spider,
            "handle": None,
            "cancel_requested": True,
        }

        with patch.object(
            thread_adapter.wire_codec,
            "handle_to_dict",
            return_value={"id": "handle"},
        ):
            result = await thread_adapter._execute(
                spider, step, "run-1", emit_log, {}
            )

        self.assertEqual(result["status"], "cancelled")
        spider.cancel.assert_called_once_with(handle)
        self.assertTrue(any(text == "thread cancelled" for text, *_ in logs))

    async def test_cancel_handler_rejects_unknown_step(self):
        result = await thread_adapter._cancel_handler({
            "run_id": "missing",
            "step_id": "step",
        })
        self.assertEqual(result["accepted"], False)
        self.assertEqual(result["reason"], "not_found")


class RunEngineCancelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        for task in list(run_engine._tasks.values()):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        run_engine._active_steps.clear()
        run_engine._tasks.clear()

    async def test_cancel_run_retries_registration_race(self):
        async def sleeper():
            await asyncio.sleep(60)

        task = asyncio.create_task(sleeper())
        step = SimpleNamespace(kind="build", spider="forgejo", id="build")
        run_engine._tasks["run-1"] = task
        run_engine._active_steps["run-1"] = step

        with patch.object(
            run_engine,
            "cancel_step",
            new=AsyncMock(side_effect=[False, False, True]),
        ) as cancel:
            accepted = await run_engine.cancel_run("run-1")

        self.assertTrue(accepted)
        self.assertEqual(cancel.await_count, 3)

    async def test_cancel_run_rejects_missing_runtime(self):
        self.assertFalse(await run_engine.cancel_run("missing"))


class ProductionDefaultsTests(unittest.TestCase):
    def test_admin_default_is_forbidden_in_prod(self):
        from auth import security

        with patch.dict(os.environ, {"ENV": "production"}, clear=False):
            with self.assertRaises(RuntimeError):
                security._env_value(
                    "ADMIN_PASSWORD",
                    "admin",
                    security.BAD_ADMIN_PASSWORDS,
                )


if __name__ == "__main__":
    unittest.main()
