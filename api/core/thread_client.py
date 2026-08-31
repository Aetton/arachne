"""Thread client — how Arachne plucks a thread over the bus.

Hides bus.request + log subscription behind one call. The orchestrator asks the
bus to run a step and receives logs, Artifacts for scenario chaining, and
RunOutputs for the result rail.
"""
from __future__ import annotations

from typing import Callable

from core.bus import get_bus
from core import subjects, wire_codec
from core.types import RunStatus

STEP_TIMEOUT = 7200.0

LogCB = Callable[[str, str, int, str], None]


async def run_step(run_id: str, kind: str, spider_name: str, step_dict: dict,
                   on_log: LogCB, context: dict | None = None) -> dict:
    """Run one step through the bus.

    Returns {status, handle, artifacts, outputs, error}. `artifacts` remains the
    machine-consumable compatibility channel; `outputs` is the user-visible one.
    """
    bus = get_bus()
    step_id = step_dict["id"]
    log_subject = subjects.log(run_id, step_id)

    async def _log_handler(msg: dict):
        on_log(msg.get("text", ""), msg.get("stream", "stdout"),
               msg.get("seq", 0), msg.get("step_id", step_id))

    subscription = await bus.subscribe(log_subject, _log_handler)
    try:
        payload = {
            "run_id": run_id,
            "spider": spider_name,
            "step": step_dict,
            "context": context or {},
        }
        result = await bus.request(subjects.run(kind, spider_name), payload,
                                   timeout=STEP_TIMEOUT)
    finally:
        await bus.unsubscribe(subscription)

    if result.get("error") and result.get("status") is None:
        return {
            "status": RunStatus.FAILED,
            "handle": None,
            "artifacts": [],
            "outputs": [],
            "error": {
                "type": "TransportError",
                "message": result["error"],
                "details": {"subject": result.get("subject")},
            },
        }

    status = RunStatus(result.get("status", "failed"))
    handle = (wire_codec.handle_from_dict(result["handle"])
              if result.get("handle") else None)
    arts = [wire_codec.artifact_from_dict(a) for a in result.get("artifacts", [])]
    outputs = [wire_codec.output_from_dict(o) for o in result.get("outputs", [])]

    # Old remote responders may not know outputs yet. Keep mixed-version NATS
    # deployments working by lifting their artifacts locally.
    if not outputs:
        from core.types import RunOutput
        outputs = [RunOutput.from_artifact(a) for a in arts]

    return {
        "status": status,
        "handle": handle,
        "artifacts": arts,
        "outputs": outputs,
        "error": result.get("error"),
    }


async def cancel_step(run_id: str, kind: str, spider_name: str, step_id: str):
    """Signal a running step to cancel. Fire-and-forget over the bus."""
    await get_bus().publish(subjects.cancel(kind, spider_name),
                            {"run_id": run_id, "step_id": step_id})
