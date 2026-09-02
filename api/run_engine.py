"""Bridge between the HTTP layer and the orchestrator core.

Keeps a live in-memory log buffer, persists run output panels, and exposes fire()
as the single entrypoint every trigger uses. The historical Run.artifacts JSON
column now stores serialized RunOutput entries; artifact-backed outputs retain
legacy top-level artifact fields so old routes keep working.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from collections import defaultdict

from database import SessionLocal, Run, utcnow
import config_loader
import scenario_store
import managed_machines

from core.registry import load_plugins, all_triggers
from core import orchestrator, wire_codec
from core.types import Artifact, RunOutput, LogLine, RunStatus

_live: dict[str, list[dict]] = defaultdict(list)
_done: dict[str, bool] = {}
_status: dict[str, RunStatus] = {}
_outputs: dict[str, list[dict]] = defaultdict(list)
_artifact_output_indexes: dict[str, dict[str, int]] = defaultdict(dict)

_initialized = False


def _reconcile_orphaned_runs() -> int:
    """Close runs left marked as running by a previous Arachne process.

    Runtime tasks, spider handles and adapter state are process-local. Once the
    process restarts there is nothing the new process can resume or cancel, so a
    persisted ``running`` row is necessarily orphaned and must not stay live in
    the UI forever.
    """
    db = SessionLocal()
    try:
        runs = db.query(Run).filter(Run.status == "running").all()
        if not runs:
            return 0

        completed_at = utcnow()
        for run in runs:
            try:
                records = json.loads(run.log or "[]")
                if not isinstance(records, list):
                    records = []
            except (TypeError, ValueError):
                records = []

            seq = max(
                (int(item.get("seq", -1)) for item in records if isinstance(item, dict)),
                default=-1,
            ) + 1
            records.append({
                "step_id": "",
                "seq": seq,
                "stream": "stderr",
                "text": (
                    "ARACHNE ERROR: run was interrupted by an Arachne restart; "
                    "runtime state was lost"
                ),
            })
            run.status = RunStatus.FAILED.value
            run.completed_at = completed_at
            run.log = json.dumps(records, ensure_ascii=False)

        db.commit()
        print(f"[run_engine] reconciled {len(runs)} orphaned running run(s)")
        return len(runs)
    finally:
        db.close()


def init():
    """Load plugins, reconcile stale runs and wire declarative triggers."""
    global _initialized
    if _initialized:
        return
    _reconcile_orphaned_runs()
    load_plugins("plugins")
    _wire_triggers()
    _initialized = True


def _wire_triggers():
    for key, scn in config_loader.all_scenarios().items():
        for tcfg in scn.get("triggers", []) or []:
            ttype = tcfg.get("type")
            if not ttype or ttype == "manual":
                continue
            trig_cls = all_triggers().get(ttype)
            if not trig_cls:
                print(f"[run_engine] unknown trigger '{ttype}' on scenario '{key}'")
                continue
            trig_cls(fire_async).setup(key, tcfg)


def new_run_id() -> str:
    return str(uuid.uuid4())


def _create_run(run_id: str, scenario_key: str, scenario: dict, params: dict) -> None:
    db = SessionLocal()
    try:
        stored = scenario_store.get_published(db, scenario_key)
        db.add(Run(id=run_id, user_id=params.get("__user_id__", 0),
                   scenario=scenario_key,
                   scenario_version_id=stored[1].id if stored else None,
                   scenario_snapshot=scenario,
                   params={k: v for k, v in params.items() if not k.startswith("__")},
                   status="running"))
        db.commit()
    finally:
        db.close()


def _persist_run(run_id: str, status, live: list[dict], outputs: list[dict]) -> None:
    db = SessionLocal()
    try:
        run = db.get(Run, run_id)
        if run:
            run.status = status.value if isinstance(status, RunStatus) else str(status)
            run.completed_at = utcnow()
            run.log = json.dumps(live, ensure_ascii=False)
            run.artifacts = outputs
            db.commit()
    finally:
        db.close()


def _log_sink(run_id: str, line: LogLine):
    _live[run_id].append({
        "step_id": line.step_id or "",
        "seq": line.seq,
        "stream": line.stream,
        "text": line.text,
    })


def _artifact_sink(run_id: str, user_id: int | None, step_id: str, artifact: Artifact) -> None:
    """Keep lifecycle registration separate from human-facing output storage."""
    managed_machines.register_artifact(run_id, user_id, artifact)


def _artifact_key(artifact: Artifact) -> str:
    return f"{artifact.type}:{artifact.location}:{artifact.name}"


def _output_sink(run_id: str, step_id: str, output: RunOutput) -> None:
    """Persist one RunOutput as one bottom-rail panel."""
    index = len(_outputs[run_id])
    if output.artifact is not None:
        _artifact_output_indexes[run_id][_artifact_key(output.artifact)] = index

    item = wire_codec.output_to_dict(output)
    item["step_id"] = step_id

    artifact_key = str((output.metadata or {}).get("artifact_key") or "")
    for link in item.get("links", []):
        if link.get("href") == "__arachne_vm_console__":
            artifact_index = _artifact_output_indexes[run_id].get(artifact_key)
            if artifact_index is not None:
                link["href"] = f"/runs/{run_id}/artifacts/{artifact_index}/console"
            else:
                link["href"] = "#"
                link["disabled"] = True

    _outputs[run_id].append(item)


def _prepare_params(params: dict, user_id: int | None = None) -> dict:
    p = dict(params)
    if user_id is not None:
        p["__user_id__"] = user_id
    return p


def _get_scenario(scenario_key: str) -> dict:
    scenario = config_loader.get_scenario(scenario_key)
    if not scenario:
        raise KeyError(f"unknown scenario {scenario_key}")
    return scenario


def _start_task(run_id: str, scenario_key: str, scenario: dict, params: dict) -> None:
    loop = asyncio.get_running_loop()
    loop.create_task(_execute(run_id, scenario_key, scenario, params))


def _init_runtime(run_id: str) -> None:
    _live[run_id] = []
    _done[run_id] = False
    _status[run_id] = RunStatus.RUNNING
    _outputs[run_id] = []
    _artifact_output_indexes[run_id] = {}


async def fire_async(scenario_key: str, params: dict, source: str = "manual") -> str:
    scenario = _get_scenario(scenario_key)
    run_id = new_run_id()
    await asyncio.to_thread(_create_run, run_id, scenario_key, scenario, params)
    _init_runtime(run_id)
    _start_task(run_id, scenario_key, scenario, params)
    return run_id


def fire(scenario_key: str, params: dict, source: str = "manual") -> str:
    """Synchronous compatibility entrypoint."""
    scenario = _get_scenario(scenario_key)
    run_id = new_run_id()
    _create_run(run_id, scenario_key, scenario, params)
    _init_runtime(run_id)
    _start_task(run_id, scenario_key, scenario, params)
    return run_id


async def start_run_async(user_id: int, scenario_key: str, params: dict) -> str:
    return await fire_async(scenario_key, _prepare_params(params, user_id), source="manual")


def start_run(user_id: int, scenario_key: str, params: dict) -> str:
    return fire(scenario_key, _prepare_params(params, user_id), source="manual")


async def _execute(run_id: str, scenario_key: str, scenario: dict, params: dict):
    clean = {k: v for k, v in params.items() if not k.startswith("__")}
    user_id = params.get("__user_id__")
    try:
        status = await orchestrator.run_scenario(
            run_id,
            scenario_key,
            scenario,
            clean,
            _log_sink,
            user_id=user_id,
            artifact_sink=lambda rid, sid, artifact: _artifact_sink(
                rid, user_id, sid, artifact
            ),
            output_sink=_output_sink,
        )
    except Exception as exc:  # noqa: BLE001
        _live[run_id].append({"step_id": "", "seq": 0, "stream": "stderr",
                              "text": f"ARACHNE ERROR: {exc}"})
        status = RunStatus.FAILED

    await asyncio.to_thread(
        _persist_run,
        run_id,
        status,
        list(_live[run_id]),
        list(_outputs[run_id]),
    )
    _status[run_id] = status
    _done[run_id] = True


def live_records(run_id: str) -> list[dict]:
    return _live.get(run_id, [])


def live_lines(run_id: str) -> list[str]:
    return [rec.get("text", "") for rec in _live.get(run_id, [])]


def live_outputs(run_id: str) -> list[dict]:
    return list(_outputs.get(run_id, []))


def live_artifacts(run_id: str) -> list[dict]:
    """Compatibility alias; these entries are RunOutputs now."""
    return live_outputs(run_id)


def get_status(run_id: str) -> RunStatus:
    return _status.get(run_id, RunStatus.PENDING)


def is_done(run_id: str) -> bool:
    return _done.get(run_id, False)
