"""Event facade over the bus. Public API (emit/subscribe) is unchanged for
callers; underneath it routes through the pluggable bus so events work the same
in-process or across NATS.

emit() is async (called from the async orchestrator). subscribe() stays sync —
it registers a handler; the registration is bridged to the bus.
"""
from __future__ import annotations

import asyncio
from typing import Callable

from core.bus import get_bus

# known event subjects (NATS-style dotted names)
RUN_STARTED = "arachne.event.run.started"
RUN_COMPLETED = "arachne.event.run.completed"
RUN_FAILED = "arachne.event.run.failed"

# back-compat aliases (old code used these constants as plain names)
_ALIASES = {
    "run.started": RUN_STARTED,
    "run.completed": RUN_COMPLETED,
    "run.failed": RUN_FAILED,
}

# pending subscriptions registered before the bus loop is running
_pending: list[tuple[str, Callable]] = []
_wired = False


def _norm(subject: str) -> str:
    return _ALIASES.get(subject, subject)


async def emit(subject: str, payload: dict) -> None:
    await get_bus().publish(_norm(subject), payload)


def subscribe(subject: str, cb: Callable[[dict], None]) -> None:
    """Register a handler. If the bus loop isn't up yet, queue it; wire() flushes."""
    subject = _norm(subject)
    if _wired:
        asyncio.create_task(get_bus().subscribe(subject, cb))
    else:
        _pending.append((subject, cb))


async def wire() -> None:
    """Flush queued subscriptions onto the bus. Called once at startup after the
    bus is started."""
    global _wired
    for subject, cb in _pending:
        await get_bus().subscribe(subject, cb)
    _pending.clear()
    _wired = True
