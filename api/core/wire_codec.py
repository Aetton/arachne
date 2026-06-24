"""Wire codec — types crossing the bus travel as plain dicts.

Defines the bus payload shape once so adapter and client never drift.
"""
from __future__ import annotations

from core.types import RunHandle, Artifact, StepSpec, RunError


def handle_to_dict(h: RunHandle) -> dict:
    return {"spider": h.spider, "external_id": h.external_id, "metadata": h.metadata}


def handle_from_dict(d: dict) -> RunHandle:
    return RunHandle(spider=d["spider"], external_id=d["external_id"],
                     metadata=d.get("metadata", {}))


def artifact_to_dict(a: Artifact) -> dict:
    return {"name": a.name, "type": a.type, "location": a.location,
            "download_url": a.download_url, "metadata": a.metadata}


def artifact_from_dict(d: dict) -> Artifact:
    return Artifact(name=d["name"], type=d.get("type", ""),
                    location=d.get("location", ""),
                    download_url=d.get("download_url"),
                    metadata=d.get("metadata", {}))


def error_to_dict(e: RunError | None) -> dict | None:
    return e.to_dict() if e else None


def error_from_dict(d: dict | None) -> RunError | None:
    if not d:
        return None
    return RunError(type=d.get("type", "Error"), message=d.get("message", ""),
                    details=d.get("details", {}))


def step_to_dict(s: StepSpec) -> dict:
    return {"id": s.id, "spider": s.spider, "action": s.action, "kind": s.kind,
            "with_": _serialize_with(s.with_), "needs": s.needs}


def _serialize_with(w: dict) -> dict:
    """Artifact objects threaded via ${step.artifact} must cross the bus as
    dicts. Scalars pass through untouched."""
    out = {}
    for k, v in w.items():
        if isinstance(v, Artifact):
            out[k] = {"__artifact__": True, **artifact_to_dict(v)}
        else:
            out[k] = v
    return out


def step_from_dict(d: dict) -> StepSpec:
    raw = d.get("with_", {})
    rehydrated = {}
    for k, v in raw.items():
        if isinstance(v, dict) and v.get("__artifact__"):
            rehydrated[k] = artifact_from_dict(v)
        else:
            rehydrated[k] = v
    return StepSpec(id=d["id"], spider=d["spider"], action=d.get("action", "run"),
                    kind=d.get("kind", "build"), with_=rehydrated,
                    needs=d.get("needs", []))
