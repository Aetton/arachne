"""Koji BuildSpider.

Submits RPM builds to a Koji hub and mirrors task state, logs and RPM artifacts
back into the Arachne Weave contract.

Connection/authentication is delegated to a standard Koji profile. This keeps
Kerberos, client certificate and password-auth details in Koji's own client
configuration instead of duplicating them in Arachne.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import AsyncIterator

from core.registry import register_spider
from core.spider import BuildSpider
from core.types import Artifact, LogLine, RunHandle, RunStatus, StepSpec


KOJI_PROFILE = os.getenv("KOJI_PROFILE", "koji")
KOJI_POLL_INTERVAL = float(os.getenv("KOJI_POLL_INTERVAL", "2"))


def _load_koji():
    import koji
    from koji_cli.lib import activate_session

    return koji, activate_session


class KojiSpider(BuildSpider):
    NAME = "koji"

    def __init__(self):
        self._runs: dict[str, dict] = {}

    @staticmethod
    def _profile_name(step: StepSpec | None = None) -> str:
        if step is not None:
            value = step.with_.get("profile")
            if value:
                return str(value)
        return KOJI_PROFILE

    def _connect(self, profile: str):
        koji, activate_session = _load_koji()
        module = koji.get_profile_module(profile)
        options = dict(vars(module.config))
        session = module.ClientSession(module.config.server, options)
        activate_session(session, options)
        return module, session

    def healthcheck(self) -> bool:
        try:
            _, session = self._connect(KOJI_PROFILE)
            session.echo("arachne")
            return True
        except Exception:
            return False

    @staticmethod
    def _map_task_state(module, state: object) -> RunStatus:
        states = getattr(module, "TASK_STATES", {}) or {}

        def code(name: str, fallback: int) -> int:
            try:
                return int(states[name])
            except Exception:
                return fallback

        value = int(state)
        if value == code("CLOSED", 2):
            return RunStatus.SUCCESS
        if value == code("CANCELED", 3):
            return RunStatus.CANCELLED
        if value == code("FAILED", 5):
            return RunStatus.FAILED
        if value in {code("FREE", 0), code("ASSIGNED", 4)}:
            return RunStatus.PENDING
        return RunStatus.RUNNING

    @staticmethod
    def _build_options(w: dict) -> dict:
        opts = {}
        for key in ("scratch", "skip_tag", "fail_fast"):
            if key in w:
                opts[key] = bool(w[key])
        if w.get("arches"):
            arches = w["arches"]
            if isinstance(arches, str):
                arches = [item for item in arches.replace(",", " ").split() if item]
            opts["arch_override"] = " ".join(str(item) for item in arches)
        if w.get("wait_repo"):
            opts["wait_repo"] = True
        if w.get("wait_builds"):
            value = w["wait_builds"]
            if isinstance(value, str):
                value = [item.strip() for item in value.split(",") if item.strip()]
            opts["wait_builds"] = list(value)
        return opts

    def dispatch(self, step: StepSpec, ctx) -> RunHandle:
        w = step.with_
        source = w.get("source") or w.get("src")
        target = w.get("target")
        if not source or not target:
            raise KeyError(
                "koji spider needs 'source' (or 'src') and 'target' in step.with"
            )

        profile = self._profile_name(step)
        module, session = self._connect(profile)
        opts = self._build_options(w)
        priority = int(w["priority"]) if w.get("priority") is not None else None
        channel = str(w["channel"]) if w.get("channel") else None

        task_id = session.build(
            str(source),
            str(target),
            opts,
            priority=priority,
            channel=channel,
        )
        if task_id is None:
            raise RuntimeError("Koji accepted build request but returned no task id")

        key = str(task_id)
        self._runs[key] = {
            "task_id": int(task_id),
            "profile": profile,
            "source": str(source),
            "target": str(target),
            "module": module,
            "session": session,
            "status": RunStatus.PENDING,
            "artifacts": [],
            "offsets": {},
            "seen_tasks": set(),
            "last_state": None,
            "error": None,
            "scratch": bool(opts.get("scratch")),
        }
        weburl = str(getattr(module.config, "weburl", "") or "").rstrip("/")
        return RunHandle(
            spider=self.NAME,
            external_id=key,
            metadata={
                "koji_task_id": int(task_id),
                "profile": profile,
                "source": str(source),
                "target": str(target),
                "task_url": f"{weburl}/taskinfo?taskID={task_id}" if weburl else "",
            },
        )

    @staticmethod
    def _task_ids(session, root_task_id: int) -> list[int]:
        ids = {int(root_task_id)}
        try:
            descendants = session.getTaskDescendents(int(root_task_id), request=False) or {}
            for parent, children in descendants.items():
                try:
                    ids.add(int(parent))
                except (TypeError, ValueError):
                    pass
                for child in children or []:
                    if isinstance(child, dict):
                        child = child.get("id")
                    try:
                        ids.add(int(child))
                    except (TypeError, ValueError):
                        pass
        except Exception:
            pass
        return sorted(ids)

    def _task_info(self, state: dict) -> dict:
        info = state["session"].getTaskInfo(state["task_id"], request=False, strict=True)
        state["status"] = self._map_task_state(state["module"], info["state"])
        state["last_state"] = info["state"]
        return info

    def _read_log_delta(self, state: dict, task_id: int, filename: str) -> list[str]:
        key = (task_id, filename)
        offset = int(state["offsets"].get(key, 0))
        chunk = state["session"].downloadTaskOutput(
            task_id,
            filename,
            offset=offset,
            size=-1,
        )
        if chunk is None:
            return []
        if isinstance(chunk, bytes):
            text = chunk.decode("utf-8", errors="replace")
            consumed = len(chunk)
        else:
            text = str(chunk)
            consumed = len(text.encode("utf-8"))
        if not text:
            return []
        state["offsets"][key] = offset + consumed
        return text.replace("\r\n", "\n").replace("\r", "\n").splitlines()

    def _log_updates(self, state: dict) -> list[LogLine]:
        lines: list[LogLine] = []
        session = state["session"]
        for task_id in self._task_ids(session, state["task_id"]):
            try:
                outputs = session.listTaskOutput(task_id, stat=True) or {}
            except Exception:
                continue
            names = outputs.keys() if isinstance(outputs, dict) else outputs
            for filename in names or []:
                filename = str(filename)
                if filename not in {"build.log", "root.log", "state.log", "mock_output.log"}:
                    continue
                try:
                    fresh = self._read_log_delta(state, task_id, filename)
                except Exception:
                    continue
                if fresh:
                    lines.append(LogLine(
                        f"::group::Koji task {task_id}: {filename}",
                        "system",
                    ))
                    lines.extend(LogLine(line) for line in fresh)
                    lines.append(LogLine("::endgroup::", "system"))
        return lines

    def _collect_artifacts(self, state: dict) -> None:
        module = state["module"]
        session = state["session"]
        artifacts: list[Artifact] = []
        seen: set[str] = set()

        builds = session.listBuilds(taskID=state["task_id"]) or []
        topurl = str(getattr(module.config, "topurl", "") or "")
        pathinfo = module.PathInfo(topdir=topurl) if topurl else None

        for build in builds:
            build_id = build.get("id") or build.get("build_id")
            if build_id is None:
                continue
            for rpm in session.listBuildRPMs(build_id) or []:
                name = (
                    f"{rpm.get('name')}-{rpm.get('version')}-{rpm.get('release')}"
                    f".{rpm.get('arch')}.rpm"
                )
                location = str(rpm.get("id") or name)
                key = f"rpm:{location}"
                if key in seen:
                    continue
                seen.add(key)
                download_url = None
                if pathinfo is not None:
                    try:
                        download_url = pathinfo.rpm(rpm)
                    except Exception:
                        pass
                artifacts.append(Artifact(
                    name=name,
                    type="rpm",
                    location=location,
                    download_url=download_url,
                    metadata={
                        "rpm_id": rpm.get("id"),
                        "build_id": build_id,
                        "name": rpm.get("name"),
                        "version": rpm.get("version"),
                        "release": rpm.get("release"),
                        "arch": rpm.get("arch"),
                        "profile": state["profile"],
                        "koji_task_id": state["task_id"],
                    },
                ))

        state["artifacts"] = artifacts

    async def stream_logs(self, handle: RunHandle) -> AsyncIterator[LogLine]:
        state = self._runs[handle.external_id]
        yield LogLine(
            f"Koji build submitted: task {state['task_id']} → "
            f"{state['target']} from {state['source']}",
            "system",
        )

        last_status = None
        while True:
            for line in await asyncio.to_thread(self._log_updates, state):
                yield line

            try:
                await asyncio.to_thread(self._task_info, state)
            except Exception as exc:
                state["status"] = RunStatus.FAILED
                state["error"] = str(exc)
                yield LogLine(f"Koji status polling failed: {exc}", "stderr")
                return

            if state["status"] != last_status:
                last_status = state["status"]
                yield LogLine(
                    f"Koji task {state['task_id']}: {state['status'].value}",
                    "system",
                )

            if state["status"].is_terminal:
                for line in await asyncio.to_thread(self._log_updates, state):
                    yield line
                if state["status"] == RunStatus.SUCCESS:
                    try:
                        await asyncio.to_thread(self._collect_artifacts, state)
                    except Exception as exc:
                        state["error"] = f"artifact collection failed: {exc}"
                        yield LogLine(state["error"], "stderr")
                return

            await asyncio.sleep(KOJI_POLL_INTERVAL)

    def get_status(self, handle: RunHandle) -> RunStatus:
        return self._runs[handle.external_id]["status"]

    def get_artifacts(self, handle: RunHandle) -> list[Artifact]:
        return list(self._runs[handle.external_id].get("artifacts", []))

    def cancel(self, handle: RunHandle) -> bool:
        state = self._runs.get(handle.external_id)
        if not state:
            return False
        try:
            state["session"].cancelTask(state["task_id"], recurse=True)
            state["status"] = RunStatus.CANCELLED
            return True
        except Exception as exc:
            state["error"] = str(exc)
            return False


register_spider(KojiSpider())
