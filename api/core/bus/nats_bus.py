"""NATS bus — for multi-process / multi-host Arachne.

Same four primitives over NATS subjects. Enable with BUS_BACKEND=nats and
NATS_URL=nats://host:4222. Requires `nats-py` (declared optional).

Threads (drivers) can now live in separate processes: each driver process calls
bus.reply(subject, handler) for its thread subject; the spider calls
bus.request(subject, ...) and NATS routes it. The core code is identical to the
in-memory path — only the backend swaps.
"""
from __future__ import annotations

import json
import os

from core.bus.base import Bus, EventHandler, ReplyHandler

NATS_URL = os.getenv("NATS_URL", "nats://127.0.0.1:4222")


class NatsBus(Bus):
    NAME = "nats"

    def __init__(self):
        self._nc = None
        self._subs = []

    async def start(self) -> None:
        import nats  # imported lazily so the dep is optional
        self._nc = await nats.connect(NATS_URL)

    async def stop(self) -> None:
        if self._nc:
            await self._nc.drain()
            self._nc = None

    async def publish(self, subject: str, payload: dict) -> None:
        await self._nc.publish(subject, json.dumps(payload).encode())

    async def subscribe(self, subject: str, handler: EventHandler) -> None:
        async def _cb(msg):
            data = json.loads(msg.data.decode() or "{}")
            res = handler(data)
            if hasattr(res, "__await__"):
                await res
        sub = await self._nc.subscribe(subject, cb=_cb)
        self._subs.append(sub)

    async def request(self, subject: str, payload: dict, timeout: float = 30.0) -> dict:
        try:
            msg = await self._nc.request(
                subject, json.dumps(payload).encode(), timeout=timeout)
            return json.loads(msg.data.decode() or "{}")
        except Exception as exc:  # noqa: BLE001  (nats.errors.NoRespondersError etc.)
            return {"error": str(exc), "subject": subject}

    async def reply(self, subject: str, handler: ReplyHandler) -> None:
        async def _cb(msg):
            data = json.loads(msg.data.decode() or "{}")
            res = handler(data)
            if hasattr(res, "__await__"):
                res = await res
            await msg.respond(json.dumps(res or {}).encode())
        sub = await self._nc.subscribe(subject, cb=_cb)
        self._subs.append(sub)
