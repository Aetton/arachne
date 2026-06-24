"""Core orchestrator types. No backend-specific code here."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (RunStatus.SUCCESS, RunStatus.FAILED, RunStatus.CANCELLED)


@dataclass
class RunHandle:
    """Opaque handle a spider issues for one dispatched step.
    external_id holds the backend's own id (forgejo run_id, pid, salt jid...)."""
    spider: str
    external_id: str
    metadata: dict = field(default_factory=dict)


@dataclass
class LogLine:
    text: str
    stream: str = "stdout"        # stdout | stderr | system
    seq: int = 0                  # per-step monotonic sequence (ordering)
    step_id: str = ""             # which step emitted it
    ts: float = 0.0


@dataclass
class RunError:
    """Structured failure — so a failed run isn't a dull brick."""
    type: str = "Error"           # BackendError | DispatchError | Timeout | ...
    message: str = ""
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"type": self.type, "message": self.message, "details": self.details}


@dataclass
class Artifact:
    """Unified artifact across all backends. `type` drives UI rendering and how
    downstream steps consume it."""
    name: str
    type: str                      # nexus | forgejo | vm | host | ...
    location: str = ""             # repo/path, run_id, vm-id — backend specific
    download_url: str | None = None
    metadata: dict = field(default_factory=dict)

    def field_value(self, key: str) -> Any:
        """Resolve ${step.<key>}. 'artifact' returns self; otherwise metadata."""
        if key == "artifact":
            return self
        if key in self.metadata:
            return self.metadata[key]
        return getattr(self, key, None)


@dataclass
class StepSpec:
    """One step parsed from a scenario."""
    id: str
    spider: str
    action: str                    # build | provision | deploy | ...
    kind: str = "build"            # build | provision — for subject routing
    with_: dict = field(default_factory=dict)
    needs: list[str] = field(default_factory=list)


@dataclass
class StepResult:
    step_id: str
    status: RunStatus
    handle: RunHandle | None = None
    artifacts: list[Artifact] = field(default_factory=list)
    error: "RunError | None" = None

    @property
    def primary(self) -> Artifact | None:
        return self.artifacts[0] if self.artifacts else None
