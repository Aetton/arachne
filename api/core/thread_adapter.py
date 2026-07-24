"""Thread adapter — puts a local spider onto the bus as a responder.

The spider contract is untouched: the adapter is the ONLY thing that knows the
bus. It executes exactly one step's lifecycle through one spider — it does NOT
know scenarios, needs, params, or the web's shape. That's Arachne's job.

Responsibilities:
  - expose each spider's `run` responder on the bus
  - stream log lines with a per-step sequence number (ordering under NATS)
  - return a structured result incl. error{type,message,details} on failure
  - hold a map of active run_id -> asyncio.Task and honour cancel signals
    (each spider cancels its own anchor via its own cancel())
"""
from __future__ import annotations

import asyncio
import time

from core.bus import get_bus
from core import subjects, wire_codec
from core.types import RunStatus, RunError
from core.registry import all_spiders, get_spider

# active executions on THIS host: run_key -> {"task", "spider", "handle"}
_active: dict[str, dict] = {}


def _run_key(run_id: str, step_id: str) -> str:
    return f"{run_id}:{step_id}"


async def _execute(spider, step, run_id: str, emit_log, context: dict) -> dict:
    """Drive one spider through one step. Returns the wire result dict."""
    seq = 0

    async def log(text: str, stream: str = "stdout"):
        nonlocal seq
        await emit_log(text, stream, seq, step.id)
        seq += 1

    # dispatch can do blocking backend I/O; keep it off the event loop.
    try:
        handle = await asyncio.to_thread(spider.dispatch, step, context)
    except Exception as exc:  # noqa: BLE001
        await log(f"PORTAL ERROR dispatching {step.id}: {exc}", "stderr")
        return {"status": RunStatus.FAILED.value, "handle": None, "artifacts": [],
                "error": RunError("DispatchError", str(exc),
                                  {"step": step.id, "spider": step.spider}).to_dict()}

    _active[_run_key(run_id, step.id)]["handle"] = handle

    # stream is already async by contract.
    try:
        async for line in spider.stream_logs(handle):
            await log(line.text, line.stream)
    except asyncio.CancelledError:
        try:
            await asyncio.to_thread(spider.cancel, handle)
        except Exception as exc:  # noqa: BLE001
            await log(f"cancel cleanup error: {exc}", "stderr")
        await log("thread cancelled", "system")
        return {"status": RunStatus.CANCELLED.value,
                "handle": wire_codec.handle_to_dict(handle), "artifacts": [],
                "error": RunError("Cancelled", "run cancelled by request").to_dict()}

    status = await asyncio.to_thread(spider.get_status, handle)
    arts = await asyncio.to_thread(spider.get_artifacts, handle)

    result = {
        "status": status.value,
        "handle": wire_codec.handle_to_dict(handle),
        "artifacts": [wire_codec.artifact_to_dict(a) for a in arts],
        "error": None,
    }
    if status == RunStatus.FAILED:
        reason = handle.metadata.get("error") if handle.metadata else None
        result["error"] = RunError(
            "BackendError",
            reason or f"{step.spider} reported failure",
            {"step": step.id, "spider": step.spider}).to_dict()
    return result


def _make_run_responder(expected_kind: str):
    async def _run_responder(payload: dict) -> dict:
        bus = get_bus()
        spider_name = payload["spider"]
        run_id = payload["run_id"]
        step = wire_codec.step_from_dict(payload["step"])
        context = payload.get("context") or {}
        log_subject = subjects.log(run_id, step.id)

        async def emit_log(text, stream, seq, step_id):
            await bus.publish(log_subject, {
                "run_id": run_id, "step_id": step_id, "seq": seq,
                "stream": stream, "text": text, "ts": time.time(),
            })

        try:
            spider = get_spider(spider_name)
        except KeyError as exc:
            await emit_log(f"PORTAL ERROR: {exc}", "stderr", 0, step.id)
            return {"status": RunStatus.FAILED.value, "handle": None,
                    "artifacts": [],
                    "error": RunError("UnknownSpider", str(exc)).to_dict()}

        key = _run_key(run_id, step.id)
        task = asyncio.create_task(_execute(spider, step, run_id, emit_log, context))
        _active[key] = {"task": task, "spider": spider, "handle": None}
        try:
            return await task
        finally:
            _active.pop(key, None)
    return _run_responder


async def _cancel_handler(payload: dict):
    key = _run_key(payload["run_id"], payload.get("step_id", ""))
    entry = _active.get(key)
    if entry and not entry["task"].done():
        entry["task"].cancel()


async def expose(spider):
    bus = get_bus()
    await bus.reply(subjects.run(spider.KIND, spider.NAME),
                    _make_run_responder(spider.KIND))
    await bus.subscribe(subjects.cancel(spider.KIND, spider.NAME), _cancel_handler)


async def expose_all():
    for spider in all_spiders().values():
        await expose(spider)
