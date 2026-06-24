"""Spider contracts — Arachne's brood.

Arachne is the queen spider in the centre. Spiders are her brood: small spiders
that run along threads to foreign anchors (Forgejo, Ansible, oVirt) and haul the
catch back to the centre. Each spider runs ONE step on ONE thread; it knows
nothing of scenarios, needs, params, or the web's overall shape — that is
Arachne's (the orchestrator's) job.

Two kinds share one lifecycle:
  build     — produce artifacts (tarball, rpm, installer)
  provision — produce a host/VM

Contract methods (the spider implements these; it never touches the bus):
  dispatch / stream_logs / get_status / get_artifacts / cancel / healthcheck
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from core.types import RunHandle, LogLine, RunStatus, Artifact, StepSpec


class BaseSpider(ABC):
    KIND: str = "base"      # "build" | "provision"  — part of the subject
    NAME: str = "base"      # unique key used in scenario YAML

    def healthcheck(self) -> bool:
        """Is the anchor reachable / are runners online? Default: assume yes."""
        return True

    @abstractmethod
    def dispatch(self, step: StepSpec, ctx) -> RunHandle:
        """Pluck the thread: kick off the work, return a handle to track it."""
        ...

    @abstractmethod
    async def stream_logs(self, handle: RunHandle) -> AsyncIterator[LogLine]:
        """Yield log lines (vibrations) until the work terminates."""
        if False:        # pragma: no cover  (typing: make it an async-gen)
            yield LogLine("")

    @abstractmethod
    def get_status(self, handle: RunHandle) -> RunStatus:
        ...

    def get_artifacts(self, handle: RunHandle) -> list[Artifact]:
        return []

    def cancel(self, handle: RunHandle) -> bool:
        """Cut the thread. Each spider knows how to kill its own anchor's work
        (Forgejo: cancel the run; Ansible: signal the process). Default: no-op."""
        return False


class BuildSpider(BaseSpider):
    KIND = "build"


class ProvisionSpider(BaseSpider):
    KIND = "provision"
