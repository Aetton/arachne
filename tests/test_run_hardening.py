from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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

    async def test_cancel_handler_acknowledges_active_step(self):
        task = asyncio.create_task(asyncio.sleep(60))
        thread_adapter._active["run-1:step-1"] = {
            "task": task,
            "spider": object(),
            "handle": None,
        }

        result = await thread_adapter._cancel_handler({
            "run_id": "run-1",
            "step_id": "step-1",
        })

        self.assertEqual(result, {"accepted": True})
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_cancel_handler_rejects_unknown_step(self):
        result = await thread_adapter._cancel_handler({
            "run_id": "missing",
            "step_id": "step",
        })
        self.assertEqual(result["accepted"], False)
        self.assertEqual(result["reason"], "not_found")


class RunEngineCancelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
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
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

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
