"""BuildSpider (Arachne thread → Forgejo).

Pluck model, not poll. On dispatch the spider:
  1. plucks a thread on the switchboard → one-time token
  2. POSTs the workflow dispatch, injecting build_id + callback_url + token
     into the workflow inputs
  3. waits for the thread to vibrate (the runner pushes block + final signals)

The runner reports back over HTTP to Arachne's callback routes; the switchboard
validates the token (law of the thread) and wakes the waiting driver.

A watchdog bounds the wait: if no vibration arrives within FORGEJO_SILENCE the
run is declared lost.
"""
from __future__ import annotations

import os
import time
from typing import AsyncIterator

import httpx

from core.spider import BuildSpider
from core.registry import register_spider
from core.types import RunHandle, LogLine, RunStatus, Artifact, StepSpec
from core import switchboard

FORGEJO_URL = os.getenv("FORGEJO_URL", "https://gitea.redsoft.internal").rstrip("/")
FORGEJO_TOKEN = os.getenv("FORGEJO_TOKEN", "")
FORGEJO_OWNER = os.getenv("FORGEJO_OWNER", "redsoft")
ARACHNE_URL = os.getenv("ARACHNE_URL", "https://arachne.redsoft.internal").rstrip("/")
NEXUS_URL = os.getenv("NEXUS_URL", "https://nexus.redsoft.internal").rstrip("/")
VERIFY_TLS = os.getenv("FORGEJO_VERIFY_TLS", "true").lower() != "false"

# overall watchdog: max total wait, and max silence between vibrations
FORGEJO_DEADLINE = float(os.getenv("FORGEJO_DEADLINE", "3600"))   # 1h hard cap
FORGEJO_SILENCE = float(os.getenv("FORGEJO_SILENCE", "600"))      # 10m no-signal

# component -> (repo, workflow file)
WORKFLOW_MAP = {
    "frontend":       ("frontend", "build.yml"),
    "broker":         ("broker", "build.yml"),
    "client-redos7":  ("client", "build-redos7.yml"),
    "client-redos8":  ("client", "build-redos8.yml"),
    "client-windows": ("client", "build-windows.yml"),
}


class ForgejoSpider(BuildSpider):
    NAME = "forgejo"

    def __init__(self):
        self._runs: dict[str, dict] = {}

    def _headers(self):
        return {"Authorization": f"token {FORGEJO_TOKEN}",
                "Content-Type": "application/json"}

    def healthcheck(self) -> bool:
        try:
            r = httpx.get(f"{FORGEJO_URL}/api/v1/version",
                          headers=self._headers(), timeout=5, verify=VERIFY_TLS)
            return r.status_code == 200
        except Exception:
            return False

    def dispatch(self, step: StepSpec, ctx) -> RunHandle:
        comp = step.with_.get("component", "")
        if comp not in WORKFLOW_MAP:
            raise KeyError(f"no workflow mapping for component '{comp}'")
        repo, wf = WORKFLOW_MAP[comp]

        thread = switchboard.pluck()           # stamp the thread
        build_id = thread.build_id

        # workflow inputs: build params + the callback contract
        inputs = {k: (str(v).lower() if isinstance(v, bool) else str(v))
                  for k, v in step.with_.items() if k != "component"}
        inputs["build_id"] = build_id
        inputs["arachne_callback"] = f"{ARACHNE_URL}/api/threads/{build_id}"
        inputs["arachne_token"] = thread.token

        url = (f"{FORGEJO_URL}/api/v1/repos/{FORGEJO_OWNER}/{repo}"
               f"/actions/workflows/{wf}/dispatches")
        body = {"ref": step.with_.get("branch", "main"), "inputs": inputs}

        self._runs[build_id] = {"comp": comp, "repo": repo, "wf": wf,
                                "version": inputs.get("version", "0.0.0"),
                                "status": RunStatus.PENDING, "artifacts": []}
        try:
            r = httpx.post(url, headers=self._headers(), json=body,
                           timeout=10, verify=VERIFY_TLS)
            r.raise_for_status()
            self._runs[build_id]["status"] = RunStatus.RUNNING
        except Exception as exc:  # noqa: BLE001
            self._runs[build_id]["status"] = RunStatus.FAILED
            self._runs[build_id]["error"] = str(exc)

        return RunHandle(spider=self.NAME, external_id=build_id,
                         metadata={"repo": repo, "workflow": wf})

    async def stream_logs(self, handle: RunHandle) -> AsyncIterator[LogLine]:
        bid = handle.external_id
        st = self._runs[bid]
        yield LogLine(f"plucked {st['comp']} → {st['repo']}/{st['wf']} "
                      f"(build_id={bid})", "system")

        if st["status"] == RunStatus.FAILED:
            yield LogLine(f"dispatch failed: {st.get('error','unknown')}", "stderr")
            switchboard.release(bid)
            return

        yield LogLine("waiting for runner to vibrate the thread…", "system")

        deadline = time.time() + FORGEJO_DEADLINE
        seen_blocks = 0

        while True:
            got = await switchboard.wait_pulse(bid, timeout=FORGEJO_SILENCE)
            thread = switchboard.get(bid)
            if thread is None:
                st["status"] = RunStatus.FAILED
                yield LogLine("thread lost", "stderr")
                return

            # drain any new blocks the runner pushed
            while seen_blocks < len(thread.blocks):
                blk = thread.blocks[seen_blocks]
                seen_blocks += 1
                name = blk.get("step", f"block {seen_blocks}")
                status = blk.get("status", "")
                yield LogLine(f"TASK [{name}]", "stdout")
                for ln in (blk.get("output", "") or "").splitlines():
                    yield LogLine(ln)
                marker = "ok" if status in ("ok", "success", "passed") else f"failed: {status}"
                yield LogLine(f"{marker}: [{name}]")

            if thread.final_status is not None:
                st["status"] = (RunStatus.SUCCESS if thread.final_status == "success"
                                else RunStatus.FAILED)
                self._finish(handle, thread)
                yield LogLine(f"thread settled: {thread.final_status}", "system")
                switchboard.release(bid)
                return

            if not got:
                # silence watchdog tripped
                st["status"] = RunStatus.FAILED
                yield LogLine(f"no vibration for {int(FORGEJO_SILENCE)}s — run lost",
                              "stderr")
                switchboard.release(bid)
                return

            if time.time() > deadline:
                st["status"] = RunStatus.FAILED
                yield LogLine("deadline exceeded — run lost", "stderr")
                switchboard.release(bid)
                return

    def _finish(self, handle: RunHandle, thread):
        st = self._runs[handle.external_id]
        if thread.artifacts:
            st["artifacts"] = [
                Artifact(name=a.get("name", "artifact"),
                         type=a.get("type", "nexus"),
                         location=a.get("location", ""),
                         download_url=a.get("download_url"),
                         metadata=a.get("metadata", {}))
                for a in thread.artifacts
            ]
        else:
            # fall back to the deterministic Nexus path
            comp, version = st["comp"], st["version"]
            path = f"{comp}/{version}/{comp}-{version}.tar.gz"
            st["artifacts"] = [Artifact(
                name=f"{comp}-{version}.tar.gz", type="nexus",
                location=f"dev-artifacts/{path}",
                download_url=f"{NEXUS_URL}/repository/dev-artifacts/{path}",
                metadata={"component": comp, "version": version})]

    def get_status(self, handle: RunHandle) -> RunStatus:
        return self._runs[handle.external_id]["status"]

    def get_artifacts(self, handle: RunHandle) -> list[Artifact]:
        return self._runs[handle.external_id]["artifacts"]

    def cancel(self, handle: RunHandle) -> bool:
        """Cut the thread: ask Forgejo to cancel the run, release the switchboard.
        Each spider cuts its own anchor — that's the contract."""
        bid = handle.external_id
        st = self._runs.get(bid, {})
        repo, ext_run = st.get("repo"), st.get("forgejo_run_id")
        cancelled = False
        if repo and ext_run:
            try:
                url = (f"{FORGEJO_URL}/api/v1/repos/{FORGEJO_OWNER}/{repo}"
                       f"/actions/runs/{ext_run}/cancel")
                r = httpx.post(url, headers=self._headers(), timeout=10,
                               verify=VERIFY_TLS)
                cancelled = r.status_code in (200, 202, 204)
            except Exception:  # noqa: BLE001
                cancelled = False
        switchboard.release(bid)
        return cancelled


register_spider(ForgejoSpider())
