"""The switchboard — where plucked threads report back.

When a spider plucks a thread (dispatches work to a remote runner), it registers
the thread here with a one-time token. The remote runner reports back over HTTP;
the callback route validates the token and pushes the signal into this board.
The spider waits on the board instead of polling.

Law of the thread: a signal is accepted only if its token matches the one the
spider stamped on that thread at dispatch time.
"""
from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, field


@dataclass
class Thread:
    build_id: str
    token: str
    created_at: float = field(default_factory=time.time)
    last_signal_at: float = field(default_factory=time.time)
    # incoming blocks (segment dicts): {step, status, output}
    blocks: list[dict] = field(default_factory=list)
    final_status: str | None = None     # success|failed|cancelled
    artifacts: list[dict] = field(default_factory=list)
    # async event fired on every incoming signal (block or final)
    _pulse: asyncio.Event = field(default_factory=asyncio.Event)


_threads: dict[str, Thread] = {}


def pluck(build_id: str | None = None) -> Thread:
    """Register a new thread; return it with its one-time token."""
    bid = build_id or secrets.token_hex(8)
    t = Thread(build_id=bid, token=secrets.token_urlsafe(24))
    _threads[bid] = t
    return t


def get(build_id: str) -> Thread | None:
    return _threads.get(build_id)


def _validate(build_id: str, token: str) -> Thread | None:
    t = _threads.get(build_id)
    if not t or not secrets.compare_digest(t.token, token):
        return None
    return t


def signal_block(build_id: str, token: str, block: dict) -> bool:
    """A runner reports one completed job/block. Returns False if token bad."""
    t = _validate(build_id, token)
    if not t:
        return False
    t.blocks.append(block)
    t.last_signal_at = time.time()
    t._pulse.set()
    return True


def signal_final(build_id: str, token: str, status: str,
                 artifacts: list[dict] | None = None) -> bool:
    t = _validate(build_id, token)
    if not t:
        return False
    t.final_status = status
    if artifacts:
        t.artifacts = artifacts
    t.last_signal_at = time.time()
    t._pulse.set()
    return True


async def wait_pulse(build_id: str, timeout: float) -> bool:
    """Wait for the next vibration on this thread. False on timeout."""
    t = _threads.get(build_id)
    if not t:
        return False
    try:
        await asyncio.wait_for(t._pulse.wait(), timeout=timeout)
        t._pulse.clear()
        return True
    except asyncio.TimeoutError:
        return False


def release(build_id: str):
    _threads.pop(build_id, None)
