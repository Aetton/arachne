"""CommandSpider: runs ansible-playbook locally against explicit targets.

A Brood artifact can be passed directly as a scenario input. The spider resolves
its preferred endpoint through the shared Brood target contract and exposes
stable scalar vars to playbooks.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
from typing import AsyncIterator

from core.brood import command_target_vars, is_brood_target, preferred_endpoint
from core.spider import CommandSpider
from core.registry import register_spider
from core.types import RunHandle, LogLine, RunStatus, Artifact, RunOutput, StepSpec

PLAYBOOKS_DIR = os.getenv("ANSIBLE_PLAYBOOKS_DIR", "../playbooks")
NEXUS_URL = os.getenv("NEXUS_URL", "https://nexus.redsoft.internal").rstrip("/")

_ART = re.compile(r"uploaded to (?P<repo>[\w\-]+)/(?P<path>\S+)")
_SENSITIVE = ("token", "secret", "password")


def _playbooks_dir() -> str:
    for c in [PLAYBOOKS_DIR,
              os.path.join(os.path.dirname(__file__), "..", "..", "..", "playbooks"),
              "playbooks"]:
        if os.path.isdir(c):
            return c
    return PLAYBOOKS_DIR


def _scalar(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _artifact_vars(key: str, artifact: Artifact) -> list[tuple[str, str]]:
    if is_brood_target(artifact):
        return command_target_vars(key, artifact)

    out = [
        (f"{key}_name", artifact.name),
        (f"{key}_type", artifact.type),
        (f"{key}_location", artifact.location),
    ]
    if artifact.download_url:
        out.append((f"{key}_url", artifact.download_url))
    for meta_key, meta_value in (artifact.metadata or {}).items():
        if isinstance(meta_value, (str, int, float, bool)):
            out.append((f"{key}_{meta_key}", _scalar(meta_value)))
    return [(k, v) for k, v in out if v not in (None, "")]


def _extra_vars(params: dict) -> list[str]:
    out = []
    for k, v in params.items():
        if isinstance(v, Artifact):
            for var_key, var_value in _artifact_vars(k, v):
                out += ["-e", f"{var_key}={var_value}"]
            continue
        if isinstance(v, (str, int, float, bool)):
            out += ["-e", f"{k}={_scalar(v)}"]
    return out


def _output_params(params: dict) -> dict:
    """Small, safe run summary for the UI panel."""
    out = {}
    for key, value in params.items():
        if any(word in key.lower() for word in _SENSITIVE):
            out[key] = "***"
        elif isinstance(value, Artifact):
            if is_brood_target(value):
                endpoint = preferred_endpoint(value, require_address=False)
                out[key] = endpoint.get("host") or value.name
            else:
                out[key] = value.name
        elif isinstance(value, (str, int, float, bool)):
            out[key] = value
    return out


class AnsibleLocalSpider(CommandSpider):
    NAME = "ansible-local"

    def __init__(self):
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
        self._runs[ext] = {
            "cmd": cmd,
            "playbook": playbook,
            "runner": "ansible-playbook" if cmd and cmd[0] == "ansible-playbook" else "demo",
            "lines": [],
            "status": RunStatus.PENDING,
            "artifacts": [],
            "params": step.with_,
        }
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
                    metadata={"repo": repo, "path": path},
                ))
            yield LogLine(line)
        await proc.wait()
        st["status"] = RunStatus.SUCCESS if proc.returncode == 0 else RunStatus.FAILED

    def get_status(self, handle: RunHandle) -> RunStatus:
        return self._runs[handle.external_id]["status"]

    def get_artifacts(self, handle: RunHandle) -> list[Artifact]:
        return self._runs[handle.external_id]["artifacts"]

    def get_outputs(self, handle: RunHandle) -> list[RunOutput]:
        st = self._runs[handle.external_id]
        return [RunOutput(
            kind="ansible",
            title=st["playbook"],
            data={
                "status": st["status"].value,
                "runner": st["runner"],
                "params": _output_params(st["params"]),
            },
        )]

    def cancel(self, handle: RunHandle) -> bool:
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
