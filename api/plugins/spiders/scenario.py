"""Scenario spider: run another Arachne scenario as a step.

Example:

    - id: build-auth
      spider: scenario
      action: run
      with:
        scenario: build-broker-auth
        params:
          version: "${params.version}"
          release: "${params.release}"
          branch: "${params.branch}"

The child run is a regular persisted Arachne run. Its logs are streamed into the
parent step, and its terminal status becomes the step status.
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from core.spider import BuildSpider
from core.registry import register_spider
from core.types import Artifact, LogLine, RunHandle, RunStatus, StepSpec


class ScenarioSpider(BuildSpider):
    NAME = "scenario"

    def __init__(self):
        self._runs: dict[str, dict] = {}

    def dispatch(self, step: StepSpec, ctx) -> RunHandle:
        scenario_key = step.with_.get("scenario")
        if not isinstance(scenario_key, str) or not scenario_key.strip():
            raise ValueError("scenario spider requires non-empty with.scenario")

        params = step.with_.get("params", {}) or {}
        if not isinstance(params, dict):
            raise ValueError("scenario spider with.params must be a mapping")

        ext = f"scenario:{step.id}:{id(step):x}"
        self._runs[ext] = {
            "scenario": scenario_key,
            "params": params,
            "child_run_id": None,
            "status": RunStatus.PENDING,
            "artifacts": [],
            "error": None,
        }
        return RunHandle(
            spider=self.NAME,
            external_id=ext,
            metadata={"scenario": scenario_key},
        )

    async def stream_logs(self, handle: RunHandle) -> AsyncIterator[LogLine]:
        # Late import avoids a module cycle while run_engine is loading plugins.
        import run_engine

        state = self._runs[handle.external_id]
        scenario_key = state["scenario"]
        params = state["params"]
        state["status"] = RunStatus.RUNNING

        yield LogLine(f"starting scenario '{scenario_key}'", "system")
        try:
            child_run_id = await run_engine.fire_async(
                scenario_key,
                params,
                source=f"scenario-spider:{handle.external_id}",
            )
        except Exception as exc:  # noqa: BLE001
            state["status"] = RunStatus.FAILED
            state["error"] = str(exc)
            handle.metadata["error"] = str(exc)
            yield LogLine(f"cannot start scenario '{scenario_key}': {exc}", "stderr")
            return

        state["child_run_id"] = child_run_id
        handle.metadata["child_run_id"] = child_run_id

        offset = 0
        while True:
            records = run_engine.live_records(child_run_id)
            for record in records[offset:]:
                child_step = record.get("step_id") or "scenario"
                text = record.get("text", "")
                yield LogLine(
                    f"[{scenario_key}/{child_step}] {text}",
                    record.get("stream", "stdout"),
                )
            offset = len(records)

            if run_engine.is_done(child_run_id):
                break
            await asyncio.sleep(0.2)

        # Drain records appended between the last poll and completion.
        records = run_engine.live_records(child_run_id)
        for record in records[offset:]:
            child_step = record.get("step_id") or "scenario"
            text = record.get("text", "")
            yield LogLine(
                f"[{scenario_key}/{child_step}] {text}",
                record.get("stream", "stdout"),
            )

        state["status"] = run_engine.get_status(child_run_id)
        state["artifacts"] = [
            Artifact(
                name=a.get("name") or scenario_key,
                type=a.get("type") or "scenario-artifact",
                download_url=a.get("download_url"),
                metadata={"scenario": scenario_key, "child_run_id": child_run_id},
            )
            for a in run_engine.live_artifacts(child_run_id)
        ]

        yield LogLine(
            f"scenario '{scenario_key}' ended: {state['status'].value}",
            "system",
        )

    def get_status(self, handle: RunHandle) -> RunStatus:
        return self._runs[handle.external_id]["status"]

    def get_artifacts(self, handle: RunHandle) -> list[Artifact]:
        return self._runs[handle.external_id]["artifacts"]


register_spider(ScenarioSpider())
