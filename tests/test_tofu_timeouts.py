"""Run with: PYTHONPATH=api python -m unittest discover -s tests."""
import asyncio
import importlib
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

from core.bus.inmemory import InMemoryBus
from core.bus.nats_bus import NatsBus
from core import subjects, thread_client
from core.types import RunStatus


class TimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_tofu_outlives_other_step_deadline(self):
        bus = InMemoryBus()
        async def slow(payload):
            await asyncio.sleep(.03)
            return {"status": "success"}
        for spider in ("tofu-proxmox", "other"):
            await bus.reply(subjects.run("provision", spider), slow)
        with patch.object(thread_client, "get_bus", return_value=bus), patch.object(thread_client, "STEP_TIMEOUT", .005):
            async def run(spider):
                return await thread_client.run_step("test", "provision", spider, {"id": "stand"}, lambda *args: None)
            self.assertEqual((await run("tofu-proxmox"))["status"], RunStatus.SUCCESS)
            self.assertEqual((await run("other"))["error"]["type"], "TransportError")
        self.assertFalse(bus._subs)

    async def test_unlimited_request_can_be_cancelled(self):
        bus = InMemoryBus()
        started, stopped = asyncio.Event(), asyncio.Event()
        async def slow(payload):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        await bus.reply("test", slow)
        task = asyncio.create_task(bus.request("test", {}, timeout=None))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(stopped.is_set())

    async def test_nats_forwards_unlimited_timeout(self):
        class Client:
            async def request(self, subject, payload, timeout):
                self.timeout = timeout
                return types.SimpleNamespace(data=b'{"status":"success"}')
        bus = NatsBus()
        bus._nc = Client()
        self.assertEqual(await bus.request("test", {}, timeout=None), {"status": "success"})
        self.assertIsNone(bus._nc.timeout)

    async def test_cancel_reaps_real_tofu_process(self):
        # Backend discovery is not involved; isolate DB/API imports only.
        stubs = {
            "database": types.SimpleNamespace(ManagedMachine=None, SessionLocal=None),
            "golden_images": types.SimpleNamespace(get_profile=None),
            "proxmox_api": types.SimpleNamespace(ProxmoxAPIError=RuntimeError, inspect_template=None),
        }
        with patch.dict(sys.modules, stubs):
            module = importlib.import_module("plugins.spiders.tofu_proxmox")
        spider = module.TofuProxmoxSpider()
        started = asyncio.Event()
        pid = None
        async def consume():
            nonlocal pid
            async for line in spider._run_cmd(
                [sys.executable, "-u", "-c", "import os,time; print(os.getpid()); time.sleep(60)"],
                cwd=Path.cwd(), env=os.environ.copy(),
            ):
                if line.text.isdigit():
                    pid = int(line.text)
                    started.set()
        task = asyncio.create_task(consume())
        await asyncio.wait_for(started.wait(), 3)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
