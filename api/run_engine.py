"""Bridge between the HTTP layer and the orchestrator core.

Keeps a live in-memory log buffer (for SSE/polling), persists runs + artifacts
to the DB, and exposes fire() as the single entrypoint every trigger uses.

Public interface:
    start_run(user_id, scenario_key, params) -> run_id
    start_run_async(user_id, scenario_key, params) -> run_id
    fire(scenario_key, params, source) -> run_id
    fire_async(scenario_key, params, source) -> run_id
    live_records(run_id) -> list[dict]
    live_lines(run_id) -> list[str]
    is_done(run_id) -> bool
"""
from __future__ import annotations

import asyncio
import json
import uuid
from collections import defaultdict

from database import SessionLocal, Run, utcnow
import config_loader
import scenario_store

from core.registry import load_plugins, all_triggers
from core import orchestrator
from core.types import LogLine, RunStatus

_live: dict[str, list[dict]] = defaultdict(list)   # structured log records
_done: dict[str, bool] = {}
_arts: dict[str, list[dict]] = defaultdict(list)   # artifacts accumulated per run

_initialized = False


def init():
    """Load plugins and wire declarative triggers from scenarios. Idempotent."""
    global _initialized
    if _initialized:
        return
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


def _persist_run(run_id: str, status, live: list[dict], artifacts: list[dict]) -> None:
    db = SessionLocal()
    try:
        run = db.get(Run, run_id)
        if run:
            run.status = status.value if isinstance(status, RunStatus) else str(status)
            run.completed_at = utcnow()
            run.log = json.dumps(live, ensure_ascii=False)
            run.artifacts = artifacts
            db.commit()
    finally:
        db.close()


def _log_sink(run_id: str, line: LogLine):
    """Store structured records so the UI can group by step_id with seq order."""
    _live[run_id].append({
        "step_id": line.step_id or "",
        "seq": line.seq,
        "stream": line.stream,
        "text": line.text,
    })
    # accumulate artifacts as they're announced (system lines: 'artifact: ...')
    if line.stream == "system" and line.text.startswith("artifact: "):
        body = line.text[len("artifact: "):]
        name = body.split(" [", 1)[0].strip()
        typ = ""
        url = None
        if "[" in body and "]" in body:
            typ = body.split("[", 1)[1].split("]", 1)[0]
        if "→" in body:
            url = body.split("→", 1)[1].strip()
        _arts[run_id].append({"name": name, "type": typ, "download_url": url})


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


async def fire_async(scenario_key: str, params: dict, source: str = "manual") -> str:
    scenario = _get_scenario(scenario_key)
    run_id = new_run_id()

    await asyncio.to_thread(_create_run, run_id, scenario_key, scenario, params)

    _live[run_id] = []
    _done[run_id] = False
    _arts[run_id] = []
    _start_task(run_id, scenario_key, scenario, params)
    return run_id


def fire(scenario_key: str, params: dict, source: str = "manual") -> str:
    """Synchronous compatibility entrypoint.

    Prefer fire_async() from FastAPI routes and async scheduler jobs. This function
    still requires an active event loop because it schedules the scenario task.
    """
    scenario = _get_scenario(scenario_key)
    run_id = new_run_id()
    _create_run(run_id, scenario_key, scenario, params)

    _live[run_id] = []
    _done[run_id] = False
    _arts[run_id] = []
    _start_task(run_id, scenario_key, scenario, params)
    return run_id


async def start_run_async(user_id: int, scenario_key: str, params: dict) -> str:
    return await fire_async(scenario_key, _prepare_params(params, user_id), source="manual")


def start_run(user_id: int, scenario_key: str, params: dict) -> str:
    return fire(scenario_key, _prepare_params(params, user_id), source="manual")


async def _execute(run_id: str, scenario_key: str, scenario: dict, params: dict):
    clean = {k: v for k, v in params.items() if not k.startswith("__")}
    try:
        status = await orchestrator.run_scenario(
            run_id, scenario_key, scenario, clean, _log_sink)
    except Exception as exc:  # noqa: BLE001
        _live[run_id].append({"step_id": "", "seq": 0, "stream": "stderr",
                              "text": f"ARACHNE ERROR: {exc}"})
        status = RunStatus.FAILED

    await asyncio.to_thread(
        _persist_run,
        run_id,
        status,
        list(_live[run_id]),
        list(_arts[run_id]),
    )
    _done[run_id] = True


def live_records(run_id: str) -> list[dict]:
    """Structured log records for the UI: [{step_id, seq, stream, text}]."""
    return _live.get(run_id, [])


def live_lines(run_id: str) -> list[str]:
    """Plain text log lines for the legacy SSE endpoint."""
    return [rec.get("text", "") for rec in _live.get(run_id, [])]


def is_done(run_id: str) -> bool:
    return _done.get(run_id, False)
