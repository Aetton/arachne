"""Model nats-py's sequential callback delivery on a single subscription."""
import asyncio
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'api'))
from core.bus.nats_bus import NatsBus


class NatsConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bus = NatsBus()
        self.bus._nc = SimpleNamespace(
            subscribe=AsyncMock(), drain=AsyncMock())

    async def deliver(self, value):
        msg = SimpleNamespace(data=json.dumps(value).encode(), respond=AsyncMock())
        cb = self.bus._nc.subscribe.call_args.kwargs['cb']
        await asyncio.wait_for(cb(msg), .5)
        return msg

    async def test_same_subscription_starts_both_before_either_finishes(self):
        started = []
        ready = asyncio.Event()
        release = asyncio.Event()

        async def handler(data):
            started.append(data['id'])
            if len(started) == 2:
                ready.set()
            await release.wait()
            return data

        await self.bus.reply('arachne.thread.build.forgejo.run', handler)
        first = await self.deliver({'id': 1, 'repo': 'same'})
        second = await self.deliver({'id': 2, 'repo': 'same'})
        await asyncio.wait_for(ready.wait(), .5)
        first.respond.assert_not_awaited()
        second.respond.assert_not_awaited()
        release.set()
        await asyncio.gather(*self.bus._reply_tasks)
        self.assertEqual(json.loads(first.respond.call_args.args[0])['id'], 1)
        self.assertEqual(json.loads(second.respond.call_args.args[0])['id'], 2)
        await self.bus.stop()
        self.assertFalse(self.bus._reply_tasks)

    async def test_stop_cancels_and_awaits_handlers_before_drain(self):
        started = asyncio.Event()
        cleaned = asyncio.Event()
        nc = self.bus._nc

        async def handler(data):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                nc.drain.assert_not_awaited()
                cleaned.set()

        await self.bus.reply('run', handler)
        await self.deliver({})
        await started.wait()
        await self.bus.stop()
        self.assertTrue(cleaned.is_set())
        nc.drain.assert_awaited_once()
        self.assertFalse(self.bus._reply_tasks)

    async def test_bad_request_does_not_block_next_reply(self):
        def handler(data):
            if data.get('bad'):
                raise ValueError('broken')
            return {'ok': True}

        await self.bus.reply('run', handler)
        with self.assertLogs('core.bus.nats_bus', level='ERROR'):
            bad = await self.deliver({'bad': True})
            good = await self.deliver({})
            await asyncio.gather(*self.bus._reply_tasks)
        self.assertEqual(json.loads(bad.respond.call_args.args[0])['error'], 'reply_handler_failed')
        self.assertEqual(json.loads(good.respond.call_args.args[0]), {'ok': True})
        await self.bus.stop()
