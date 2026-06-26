"""In-memory bus — default. Zero external services, single process.

pub/sub  = dict of subject -> handlers
req/reply = dict of subject -> one reply handler, called directly

Subject wildcards: a trailing '.*' matches one extra token, '.>' matches the
rest (NATS-style), so the in-memory bus behaves like the future NATS bus.
"""
from __future__ import annotations

import asyncio
import inspect
from collections import defaultdict
from dataclasses import dataclass

from core.bus.base import Bus, EventHandler, ReplyHandler


@dataclass(frozen=True)
class InMemorySubscription:
    subject: str
    handler: EventHandler


def _matches(pattern: str, subject: str) -> bool:
    if pattern == subject:
        return True
    pt, st = pattern.split("."), subject.split(".")
    for i, tok in enumerate(pt):
        if tok == ">":
            return True
        if i >= len(st):
            return False
        if tok == "*":
            continue
        if tok != st[i]:
            return False
    return len(pt) == len(st)


async def _maybe_await(result):
    if inspect.isawaitable(result):
        return await result
    return result


class InMemoryBus(Bus):
    NAME = "inmemory"

    def __init__(self):
        self._subs: dict[str, list[EventHandler]] = defaultdict(list)
        self._replies: dict[str, ReplyHandler] = {}

    async def publish(self, subject: str, payload: dict) -> None:
        for pattern, handlers in list(self._subs.items()):
            if _matches(pattern, subject):
                for h in list(handlers):
                    try:
                        await _maybe_await(h(payload))
                    except Exception as exc:  # noqa: BLE001
                        print(f"[bus] subscriber error on {subject}: {exc}")

    async def subscribe(self, subject: str, handler: EventHandler) -> InMemorySubscription:
        self._subs[subject].append(handler)
        return InMemorySubscription(subject, handler)

    async def unsubscribe(self, subscription: InMemorySubscription) -> None:
        handlers = self._subs.get(subscription.subject)
        if not handlers:
            return
        try:
            handlers.remove(subscription.handler)
        except ValueError:
            return
        if not handlers:
            self._subs.pop(subscription.subject, None)

    async def request(self, subject: str, payload: dict, timeout: float = 30.0) -> dict:
        # find the reply handler whose subject matches
        for pattern, handler in self._replies.items():
            if _matches(pattern, subject):
                try:
                    return await asyncio.wait_for(
                        _maybe_await(handler(payload)), timeout=timeout)
                except asyncio.TimeoutError:
                    return {"error": "timeout", "subject": subject}
        return {"error": "no_responder", "subject": subject}

    async def reply(self, subject: str, handler: ReplyHandler) -> InMemorySubscription:
        self._replies[subject] = handler
        return InMemorySubscription(subject, handler)