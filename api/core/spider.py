"""Spider contracts and the three Arachne operation families.

Arachne keeps orchestration in the centre. A spider executes one step against one
external system and knows nothing about the full scenario graph.

Operation families:
  weave   — produce build artifacts (rpm, installer, archive, image, ...)
  brood   — provision environments or machines
  command — execute work against resources produced by a Brood spider

All three share the same lifecycle:
  dispatch / stream_logs / get_status / get_artifacts / cancel / healthcheck
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from core.types import RunHandle, LogLine, RunStatus, Artifact, StepSpec


class BaseSpider(ABC):
    KIND: str = "base"
    NAME: str = "base"

    def healthcheck(self) -> bool:
        """Is the anchor reachable / are runners online? Default: assume yes."""
        return True

    @abstractmethod
    def dispatch(self, step: StepSpec, ctx) -> RunHandle:
        """Start the work and return a handle used to track it."""
        ...

    @abstractmethod
    async def stream_logs(self, handle: RunHandle) -> AsyncIterator[LogLine]:
        if False:  # pragma: no cover
            yield LogLine("")

    @abstractmethod
    def get_status(self, handle: RunHandle) -> RunStatus:
        ...

    def get_artifacts(self, handle: RunHandle) -> list[Artifact]:
        return []

    def cancel(self, handle: RunHandle) -> bool:
        return False


class WeaveSpider(BaseSpider):
    KIND = "weave"


class BroodSpider(BaseSpider):
    KIND = "brood"


class CommandSpider(BaseSpider):
    KIND = "command"


# Compatibility aliases for existing plugins and external extensions. New spiders
# should inherit from WeaveSpider / BroodSpider / CommandSpider directly.
class BuildSpider(WeaveSpider):
    KIND = "build"


class ProvisionSpider(BroodSpider):
    KIND = "provision"
