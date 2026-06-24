"""Bridge between the HTTP layer and the orchestrator core.

Keeps a live in-memory log buffer (for SSE/polling), persists runs + artifacts
to the DB, and exposes fire() as the single entrypoint every trigger uses.

Public interface (unchanged for main.py):
    start_run(user_id, scenario_key, params) -> run_id
    fire(scenario_key, params, source) -> run_id      (trigger entrypoint)
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
            trig_cls(fire).setup(key, tcfg)


def new_run_id() -> str:
    return str(uuid.uuid4())


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
        if "\u2192" in body:
            url = body.split("\u2192", 1)[1].strip()
        _arts[run_id].append({"name": name, "type": typ, "download_url": url})


def fire(scenario_key: str, params: dict, source: str = "manual") -> str:
    scenario = config_loader.get_scenario(scenario_key)
    if not scenario:
        raise KeyError(f"unknown scenario {scenario_key}")

    run_id = new_run_id()
    db = SessionLocal()
    db.add(Run(id=run_id, user_id=params.get("__user_id__", 0),
               scenario=scenario_key,
               params={k: v for k, v in params.items() if not k.startswith("__")},
               status="running"))
    db.commit()
    db.close()

    _live[run_id] = []
    _done[run_id] = False
    _arts[run_id] = []
    asyncio.create_task(_execute(run_id, scenario_key, scenario, params))
    return run_id


def start_run(user_id: int, scenario_key: str, params: dict) -> str:
    p = dict(params)
    p["__user_id__"] = user_id
    return fire(scenario_key, p, source="manual")


async def _execute(run_id: str, scenario_key: str, scenario: dict, params: dict):
    clean = {k: v for k, v in params.items() if not k.startswith("__")}
    try:
        status = await orchestrator.run_scenario(
            run_id, scenario_key, scenario, clean, _log_sink)
    except Exception as exc:  # noqa: BLE001
        _live[run_id].append({"step_id": "", "seq": 0, "stream": "stderr",
                              "text": f"PORTAL ERROR: {exc}"})
        status = RunStatus.FAILED

    db = SessionLocal()
    run = db.get(Run, run_id)
    if run:
        run.status = status.value if isinstance(status, RunStatus) else str(status)
        run.completed_at = utcnow()
        # persist structured log as JSON-able list of records
        run.log = json.dumps(_live[run_id], ensure_ascii=False)
        run.artifacts = _arts[run_id]
        db.commit()
    db.close()

    _done[run_id] = True


def live_records(run_id: str) -> list[dict]:
    """Structured log records for the UI: [{step_id, seq, stream, text}]."""
    return _live.get(run_id, [])


def is_done(run_id: str) -> bool:
    return _done.get(run_id, False)
