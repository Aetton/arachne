"""Orchestration loop — Arachne's job.

Arachne owns the scenario graph. Spiders own one external operation. Brood output
is normalized to the shared target contract before it enters the run context so
Command spiders can consume it without backend-specific knowledge.
"""
from __future__ import annotations

from typing import Callable

from core import events, wire_codec
from core.brood import normalize_brood_artifact
from core.context import RunContext
from core.thread_client import run_step
from core.registry import get_spider
from core.types import Artifact, StepSpec, StepResult, RunStatus, LogLine

LogSink = Callable[[str, LogLine], None]
ArtifactSink = Callable[[str, str, Artifact], None]


def _kind_of(spider_name: str) -> str:
    """Resolve legacy wire kind used in bus subjects."""
    try:
        return get_spider(spider_name).KIND
    except KeyError:
        return "build"


def _family_of(spider_name: str, kind: str) -> str:
    """Resolve the domain family independently from the wire kind.

    For remote spiders that are not registered in this process, legacy provision
    still unambiguously maps to Brood. Other unknown remote spiders remain Weave
    unless their scenario/plugin metadata is upgraded later.
    """
    try:
        return get_spider(spider_name).FAMILY
    except KeyError:
        return "brood" if kind == "provision" else "weave"


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
                       params: dict, log_sink: LogSink,
                       user_id: int | None = None,
                       artifact_sink: ArtifactSink | None = None) -> RunStatus:
    ctx = RunContext(params, user_id=user_id)
    steps = parse_steps(scenario)

    await events.emit(events.RUN_STARTED, {"scenario": scenario_key, "run_id": run_id})
    overall = RunStatus.SUCCESS

    for step in steps:
        log_sink(run_id, LogLine(f"━━━ step '{step.id}' via {step.spider} ━━━",
                                 "system", step_id=step.id))

        resolved = ctx.resolve_dict(step.with_)
        resolved_step = StepSpec(step.id, step.spider, step.action, step.kind,
                                 resolved, step.needs)
        step_dict = wire_codec.step_to_dict(resolved_step)

        def _on_log(text, stream, seq, step_id, _rid=run_id):
            log_sink(_rid, LogLine(text, stream, seq=seq, step_id=step_id))

        result = await run_step(run_id, step.kind, step.spider, step_dict, _on_log,
                                context={"user_id": ctx.user_id})

        status = result["status"]
        artifacts = result["artifacts"]
        handle = result.get("handle")
        err = wire_codec.error_from_dict(result.get("error"))

        if _family_of(step.spider, step.kind) == "brood":
            artifacts = [
                normalize_brood_artifact(artifact, spider_name=step.spider)
                for artifact in artifacts
            ]

        if err:
            log_sink(run_id, LogLine(
                f"error [{err.type}]: {err.message}", "stderr", step_id=step.id))

        ctx.record(StepResult(step.id, status, handle, artifacts, err))

        for artifact in artifacts:
            if artifact_sink:
                artifact_sink(run_id, step.id, artifact)
            tail = f" → {artifact.download_url}" if artifact.download_url else ""
            log_sink(run_id, LogLine(
                f"artifact: {artifact.name} [{artifact.type}]{tail}",
                "system",
                step_id=step.id,
            ))

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
