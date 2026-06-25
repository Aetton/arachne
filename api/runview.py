"""Build the two-level run view (steps → tasks) from structured log records.

Records look like {step_id, seq, stream, text}. We group by step_id (in first-
seen order), split each step's lines into ansible TASK blocks, and derive a
status per step and per task. No realtime line-streaming — statuses come in
blocks — so the UI renders collapsed by default.
"""
from __future__ import annotations

import re

_TASK = re.compile(r"^(TASK|PLAY|PLAY RECAP|RUNNING HANDLER)\b(?:\s*\[(?P<title>.*?)\])?")
_STEP_MARK = re.compile(r"^━+ step '(?P<id>[^']+)' via (?P<spider>\S+) ━+")


def _failed(text: str) -> bool:
    s = text.lstrip()
    return s.startswith(("fatal:", "failed:", "ARACHNE ERROR", "PORTAL ERROR", "error ["))


def build(records: list[dict], run_status: str) -> list[dict]:
    """Return [{id, spider, status, tasks:[{title, lines, status}], artifacts}]."""
    steps: list[dict] = []
    by_id: dict[str, dict] = {}

    def ensure_step(step_id: str, spider: str = "") -> dict:
        if step_id not in by_id:
            st = {"id": step_id or "output", "spider": spider,
                  "status": "pending", "tasks": [], "artifacts": [],
                  "_failed": False, "_started": False}
            by_id[step_id] = st
            steps.append(st)
        return by_id[step_id]

    for rec in records:
        text = rec.get("text", "")
        sid = rec.get("step_id", "") or ""
        stream = rec.get("stream", "stdout")

        # step boundary marker (system line) — sets spider + marks started
        m_mark = _STEP_MARK.match(text)
        if m_mark:
            st = ensure_step(m_mark.group("id"), m_mark.group("spider"))
            st["_started"] = True
            continue

        # artifact announcement (system) → attach to step
        if stream == "system" and text.startswith("artifact: "):
            st = ensure_step(sid)
            body = text[len("artifact: "):]
            name = body.split(" [", 1)[0].strip()
            url = body.split("→", 1)[1].strip() if "→" in body else None
            st["artifacts"].append({"name": name, "url": url})
            continue

        # skip the trailing "step 'x' ended: ..." noise (status derived already)
        if stream == "system" and text.startswith("step '"):
            continue

        st = ensure_step(sid)
        st["_started"] = True

        # ansible TASK header opens a new task block
        m_task = _TASK.match(text)
        if m_task:
            title = m_task.group("title") or m_task.group(1).title()
            st["tasks"].append({"title": title, "lines": [], "status": "passed"})
            continue

        # body line — append to current task (create a default one if none yet)
        if not st["tasks"]:
            st["tasks"].append({"title": "output", "lines": [], "status": "passed"})
        st["tasks"][-1]["lines"].append(text)
        if _failed(text) or stream == "stderr":
            st["tasks"][-1]["status"] = "failed"
            st["_failed"] = True

    # derive per-step status
    n = len(steps)
    for i, st in enumerate(steps):
        if st["_failed"]:
            st["status"] = "failed"
        elif st["_started"]:
            # last started step while run is still going = running
            if run_status == "running" and i == n - 1:
                st["status"] = "running"
            else:
                st["status"] = "passed"
        else:
            st["status"] = "pending"
        st.pop("_failed", None)
        st.pop("_started", None)

    return steps
