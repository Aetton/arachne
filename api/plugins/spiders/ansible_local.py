"""BuildSpider: runs ansible-playbook locally, streams output.

Falls back to a demo script when ansible/playbook is absent so the whole
pipeline is exercisable on a dev box.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
from typing import AsyncIterator

from core.spider import BuildSpider
from core.registry import register_spider
from core.types import RunHandle, LogLine, RunStatus, Artifact, StepSpec

PLAYBOOKS_DIR = os.getenv("ANSIBLE_PLAYBOOKS_DIR", "../playbooks")
NEXUS_URL = os.getenv("NEXUS_URL", "https://nexus.redsoft.internal").rstrip("/")

_ART = re.compile(r"uploaded to (?P<repo>[\w\-]+)/(?P<path>\S+)")


def _playbooks_dir() -> str:
    for c in [PLAYBOOKS_DIR,
              os.path.join(os.path.dirname(__file__), "..", "..", "..", "playbooks"),
              "playbooks"]:
        if os.path.isdir(c):
            return c
    return PLAYBOOKS_DIR


def _extra_vars(params: dict) -> list[str]:
    out = []
    for k, v in params.items():
        if isinstance(v, bool):
            v = "true" if v else "false"
        # skip Artifact objects / non-scalars
        if isinstance(v, (str, int, float)):
            out += ["-e", f"{k}={v}"]
    return out


class AnsibleLocalSpider(BuildSpider):
    NAME = "ansible-local"

    def __init__(self):
        # per-handle state: external_id -> dict(proc, lines, status, artifacts)
        self._runs: dict[str, dict] = {}

    def _command(self, playbook: str, params: dict) -> list[str]:
        pb_path = os.path.join(_playbooks_dir(), playbook)
        if shutil.which("ansible-playbook") and os.path.exists(pb_path):
            return ["ansible-playbook", pb_path, *_extra_vars(params)]
        demo = os.path.join(os.path.dirname(__file__), "..", "..", "runners", "demo_play.sh")
        return ["bash", demo, params.get("component", playbook)]

    def dispatch(self, step: StepSpec, ctx) -> RunHandle:
        playbook = step.with_.get("playbook") or f"build-{step.with_.get('component','x')}.yml"
        cmd = self._command(playbook, step.with_)
        ext = f"{step.id}-{id(self):x}"
        self._runs[ext] = {"cmd": cmd, "lines": [], "status": RunStatus.PENDING,
                           "artifacts": [], "params": step.with_}
        return RunHandle(spider=self.NAME, external_id=ext, metadata={"cmd": cmd})

    async def stream_logs(self, handle: RunHandle) -> AsyncIterator[LogLine]:
        st = self._runs[handle.external_id]
        cmd = st["cmd"]
        st["status"] = RunStatus.RUNNING
        yield LogLine(f"$ {' '.join(cmd)}", "system")

        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            env={**os.environ, "ANSIBLE_FORCE_COLOR": "0", "PYTHONUNBUFFERED": "1"},
        )
        st["proc"] = proc
        assert proc.stdout is not None
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").rstrip("\n")
            st["lines"].append(line)
            m = _ART.search(line)
            if m:
                repo, path = m.group("repo"), m.group("path")
                st["artifacts"].append(Artifact(
                    name=path.rsplit("/", 1)[-1], type="nexus",
                    location=f"{repo}/{path}",
                    download_url=f"{NEXUS_URL}/repository/{repo}/{path}",
                    metadata={"repo": repo},
                ))
            yield LogLine(line)
        await proc.wait()
        st["status"] = RunStatus.SUCCESS if proc.returncode == 0 else RunStatus.FAILED

    def get_status(self, handle: RunHandle) -> RunStatus:
        return self._runs[handle.external_id]["status"]

    def get_artifacts(self, handle: RunHandle) -> list[Artifact]:
        return self._runs[handle.external_id]["artifacts"]

    def cancel(self, handle: RunHandle) -> bool:
        """Cut the thread: SIGTERM the ansible process."""
        st = self._runs.get(handle.external_id, {})
        proc = st.get("proc")
        if proc and proc.returncode is None:
            try:
                proc.terminate()
                return True
            except ProcessLookupError:
                return False
        return False


register_spider(AnsibleLocalSpider())
