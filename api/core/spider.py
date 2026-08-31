"""Spider contracts and the three Arachne operation families.

Domain family and transport kind are intentionally separate. FAMILY is the public
Arachne taxonomy; KIND is the legacy bus subject class kept stable during the
migration of distributed responders.

Families:
  weave   — produce build artifacts
  brood   — provision environments or machines
  command — execute work against resources produced by Brood

Wire kinds remain ``build`` and ``provision`` for compatibility.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from core.types import RunHandle, LogLine, RunStatus, Artifact, StepSpec


class BaseSpider(ABC):
    FAMILY: str = "base"
    KIND: str = "build"
    NAME: str = "base"

    def healthcheck(self) -> bool:
        return True

    @abstractmethod
    def dispatch(self, step: StepSpec, ctx) -> RunHandle:
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
    FAMILY = "weave"
    KIND = "build"


class BroodSpider(BaseSpider):
    FAMILY = "brood"
    KIND = "provision"


class CommandSpider(BaseSpider):
    FAMILY = "command"
    KIND = "build"


# Compatibility names. Existing third-party spiders can migrate inheritance when
# convenient without changing their current bus subjects.
class BuildSpider(WeaveSpider):
    pass


class ProvisionSpider(BroodSpider):
    pass
