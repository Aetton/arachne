"""Bus factory. One env var swaps the whole transport.

    BUS_BACKEND=inmemory   (default)
    BUS_BACKEND=nats       (+ NATS_URL)

Everything in the core talks to `bus` (the singleton). Plugins never import this.
"""
from __future__ import annotations

import os

from core.bus.base import Bus
from core.bus.inmemory import InMemoryBus

_BACKEND = os.getenv("BUS_BACKEND", "inmemory").lower()

_instance: Bus | None = None


def get_bus() -> Bus:
    global _instance
    if _instance is None:
        _instance = _build()
    return _instance


def _build() -> Bus:
    if _BACKEND == "nats":
        from core.bus.nats_bus import NatsBus
        return NatsBus()
    return InMemoryBus()


async def start_bus():
    await get_bus().start()


async def stop_bus():
    if _instance:
        await _instance.stop()
