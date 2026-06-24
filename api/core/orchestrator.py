"""Orchestration loop — Arachne's job. Runs a scenario's steps in order, threads
each step's artifacts into the shared context for ${...} resolution, and plucks
each thread through the bus.

Arachne owns the scenario (steps, needs, params, error propagation). The thread
adapter owns one step's execution through one spider. The core knows nothing of
Forgejo/Ansible/Proxmox — only contracts.
"""
from __future__ import annotations

from typing import Callable

from core import events, wire_codec
from core.context import RunContext
from core.thread_client import run_step
from core.registry import get_spider
from core.types import StepSpec, StepResult, RunStatus, LogLine, RunError

# sink(run_id, LogLine) — where live log lines go (UI buffer + DB)
LogSink = Callable[[str, LogLine], None]


def _kind_of(spider_name: str) -> str:
    """Resolve a spider's kind for subject routing. Falls back to 'build' if the
    spider isn't locally registered (multi-process: Arachne may not host it)."""
    try:
        return get_spider(spider_name).KIND
    except KeyError:
        return "build"


def parse_steps(scenario: dict) -> list[StepSpec]:
    steps = []
    for raw in scenario.get("steps", []):
        spider = raw["spider"]
        steps.append(StepSpec(
            id=raw["id"],
            spider=spider,
            action=raw.get("action", "run"),
            kind=raw.get("kind") or _kind_of(spider),
            with_=raw.get("with", {}) or {},
            needs=raw.get("needs", []) or [],
        ))
    return steps


async def run_scenario(run_id: str, scenario_key: str, scenario: dict,
                       params: dict, log_sink: LogSink) -> RunStatus:
    """Execute all steps. Returns the overall status."""
    ctx = RunContext(params)
    steps = parse_steps(scenario)

    await events.emit(events.RUN_STARTED, {"scenario": scenario_key, "run_id": run_id})

    overall = RunStatus.SUCCESS

    for step in steps:
        log_sink(run_id, LogLine(f"━━━ step '{step.id}' via {step.spider} ━━━",
                                 "system", step_id=step.id))

        # resolve ${...} in this step's `with` against accumulated context
        resolved = ctx.resolve_dict(step.with_)
        resolved_step = StepSpec(step.id, step.spider, step.action, step.kind,
                                 resolved, step.needs)
        step_dict = wire_codec.step_to_dict(resolved_step)

        # bridge bus log lines (with seq + step_id) into the run's sink
        def _on_log(text, stream, seq, step_id, _rid=run_id):
            log_sink(_rid, LogLine(text, stream, seq=seq, step_id=step_id))

        result = await run_step(run_id, step.kind, step.spider, step_dict, _on_log)

        status = result["status"]
        artifacts = result["artifacts"]
        handle = result.get("handle")
        err = wire_codec.error_from_dict(result.get("error"))

        if err:
            log_sink(run_id, LogLine(
                f"error [{err.type}]: {err.message}", "stderr", step_id=step.id))

        ctx.record(StepResult(step.id, status, handle, artifacts, err))

        for a in artifacts:
            tail = f" → {a.download_url}" if a.download_url else ""
            log_sink(run_id, LogLine(f"artifact: {a.name} [{a.type}]{tail}",
                                     "system", step_id=step.id))

        if status != RunStatus.SUCCESS:
            log_sink(run_id, LogLine(f"step '{step.id}' ended: {status.value}",
                                     "system", step_id=step.id))
            overall = RunStatus.FAILED if status == RunStatus.FAILED else status
            break

    payload = {"scenario": scenario_key, "run_id": run_id, "status": overall.value}
    await events.emit(events.RUN_COMPLETED, payload)
    if overall == RunStatus.FAILED:
        await events.emit(events.RUN_FAILED, payload)

    return overall
