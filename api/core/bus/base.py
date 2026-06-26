"""Bus contract — the nervous system of the web.

Four primitives:
  publish / subscribe   — events (run.completed, chain triggers)
  request / reply       — calling a thread (driver) wherever it lives

The bus is hidden inside the core. Plugin contracts (drivers, triggers) never
import it: adding a new thread = implementing the driver contract, nothing more.
Swapping the bus (in-memory → NATS) and adding a thread are independent axes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable

# async handler(payload) -> None        (pub/sub)
EventHandler = Callable[[dict], Awaitable[None] | None]
# async handler(payload) -> dict        (request/reply)
ReplyHandler = Callable[[dict], Awaitable[dict] | dict]
# transport-specific subscription handle
Subscription = Any


class Bus(ABC):
    NAME: str = "base"

    @abstractmethod
    async def publish(self, subject: str, payload: dict) -> None:
        ...

    @abstractmethod
    async def subscribe(self, subject: str, handler: EventHandler) -> Subscription:
        ...

    @abstractmethod
    async def unsubscribe(self, subscription: Subscription) -> None:
        ...

    @abstractmethod
    async def request(self, subject: str, payload: dict, timeout: float = 30.0) -> dict:
        ...

    @abstractmethod
    async def reply(self, subject: str, handler: ReplyHandler) -> Subscription:
        ...

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None
