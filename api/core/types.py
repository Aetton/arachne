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
    stream: str = "stdout"
    seq: int = 0
    step_id: str = ""
    ts: float = 0.0


@dataclass
class RunError:
    """Structured failure — so a failed run isn't a dull brick."""
    type: str = "Error"
    message: str = ""
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"type": self.type, "message": self.message, "details": self.details}


@dataclass
class Artifact:
    """Machine-consumable output threaded between scenario steps."""
    name: str
    type: str
    location: str = ""
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
class RunOutput:
    """One user-visible result panel produced by a spider run.

    `kind` selects the UI renderer. `data` is JSON-shaped and backend-neutral.
    `links` contains actions such as downloads or consoles. `artifact` optionally
    anchors the panel to a machine-consumable Artifact for downstream steps.
    """
    kind: str
    title: str
    data: dict = field(default_factory=dict)
    links: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    artifact: Artifact | None = None

    @classmethod
    def from_artifact(cls, artifact: Artifact) -> "RunOutput":
        links = []
        if artifact.download_url:
            links.append({
                "label": "Download",
                "href": artifact.download_url,
                "kind": "download",
            })
        return cls(
            kind="artifact",
            title=artifact.name,
            data={"artifact_type": artifact.type, "location": artifact.location},
            links=links,
            artifact=artifact,
        )


@dataclass
class StepSpec:
    """One step parsed from a scenario."""
    id: str
    spider: str
    action: str
    kind: str = "build"
    with_: dict = field(default_factory=dict)
    needs: list[str] = field(default_factory=list)


@dataclass
class StepResult:
    step_id: str
    status: RunStatus
    handle: RunHandle | None = None
    artifacts: list[Artifact] = field(default_factory=list)
    error: "RunError | None" = None
    outputs: list[RunOutput] = field(default_factory=list)

    @property
    def primary(self) -> Artifact | None:
        return self.artifacts[0] if self.artifacts else None
