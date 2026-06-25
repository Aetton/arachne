"""BuildSpider (Arachne thread → Forgejo).

Pluck model. On dispatch the spider:
  1. plucks a thread on the switchboard → one-time token
  2. POSTs the workflow dispatch, injecting build_id + callback_url + token
  3. asks Forgejo to return run metadata when supported
  4. waits for Arachne hub telemetry from workflow actions

Forgejo's public API exposes dispatch/run/task metadata on current Forgejo, but not
runner logs. Logs are mirrored by the Forgejo utility belt actions such as
`arachne/init-pwsh`.
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

FORGEJO_URL = os.getenv("FORGEJO_URL", "https://forgejo.example.internal").rstrip("/")
FORGEJO_TOKEN = os.getenv("FORGEJO_TOKEN", "")
FORGEJO_OWNER = os.getenv("FORGEJO_OWNER", "example")
ARACHNE_URL = os.getenv("ARACHNE_URL", "https://arachne.example.internal").rstrip("/")
NEXUS_URL = os.getenv("NEXUS_URL", "https://nexus.example.internal").rstrip("/")
VERIFY_TLS = os.getenv("FORGEJO_VERIFY_TLS", "true").lower() != "false"

FORGEJO_DEADLINE = float(os.getenv("FORGEJO_DEADLINE", "3600"))
FORGEJO_SILENCE = float(os.getenv("FORGEJO_SILENCE", "600"))


class ForgejoSpider(BuildSpider):
    NAME = "forgejo"

    # keys consumed by the spider itself — everything else flows to workflow inputs
    _CONTROL_KEYS = {"component", "repo", "workflow", "owner", "ref", "branch"}

    def __init__(self):
        self._runs: dict[str, dict] = {}

    def _headers(self):
        return {"Authorization": f"token {FORGEJO_TOKEN}",
                "Content-Type": "application/json"}

    @staticmethod
    def _http_error(exc: Exception, url: str, body: dict | None = None,
                    method: str = "POST") -> str:
        """Return an operator-readable backend error, including Forgejo's body."""
        if isinstance(exc, httpx.HTTPStatusError):
            resp = exc.response
            try:
                detail = resp.json()
            except ValueError:
                detail = resp.text
            return (f"Forgejo API {resp.status_code} while {method} {url}: {detail!r}; "
                    f"request={body!r}")
        return f"{exc} (while {method} {url}; request={body!r})"

    def healthcheck(self) -> bool:
        try:
            r = httpx.get(f"{FORGEJO_URL}/api/v1/version",
                          headers=self._headers(), timeout=5, verify=VERIFY_TLS)
            return r.status_code == 200
        except Exception:
            return False

    def dispatch(self, step: StepSpec, ctx) -> RunHandle:
        w = step.with_
        repo = w.get("repo")
        wf = w.get("workflow")
        if not repo or not wf:
            raise KeyError(
                f"forgejo spider needs 'repo' and 'workflow' in step.with "
                f"(got repo={repo!r}, workflow={wf!r}). "
                f"Define them in the scenario step, not in code.")
        owner = w.get("owner", FORGEJO_OWNER)
        ref = str(w.get("ref") or w.get("branch") or "main")

        thread = switchboard.pluck()
        build_id = thread.build_id

        inputs = {k: (str(v).lower() if isinstance(v, bool) else str(v))
                  for k, v in w.items() if k not in self._CONTROL_KEYS}
        inputs["build_id"] = build_id
        inputs["arachne_callback"] = f"{ARACHNE_URL}/api/threads/{build_id}"
        inputs["arachne_token"] = thread.token

        url = (f"{FORGEJO_URL}/api/v1/repos/{owner}/{repo}"
               f"/actions/workflows/{wf}/dispatches")
        body = {"ref": ref, "inputs": inputs, "return_run_info": True}
        metadata = {"repo": repo, "workflow": wf, "owner": owner, "ref": ref}

        self._runs[build_id] = {
            "comp": w.get("component", repo),
            "repo": repo,
            "owner": owner,
            "wf": wf,
            "ref": ref,
            "version": inputs.get("version", "0.0.0"),
            "status": RunStatus.PENDING,
            "artifacts": [],
            "forgejo_run_id": None,
            "forgejo_run_number": None,
            "forgejo_jobs": [],
        }
        try:
            r = httpx.post(url, headers=self._headers(), json=body,
                           timeout=10, verify=VERIFY_TLS)
            r.raise_for_status()
            self._runs[build_id]["status"] = RunStatus.RUNNING
            if r.status_code == 201 and r.content:
                self._bind_dispatch_run_info(build_id, r.json(), metadata)
        except Exception as exc:  # noqa: BLE001
            err = self._http_error(exc, url, body)
            self._runs[build_id]["status"] = RunStatus.FAILED
            self._runs[build_id]["error"] = err
            metadata["error"] = err

        return RunHandle(spider=self.NAME, external_id=build_id, metadata=metadata)

    def _bind_dispatch_run_info(self, build_id: str, data: dict, metadata: dict):
        st = self._runs[build_id]
        run_id = data.get("id") or data.get("run_id")
        if run_id:
            st["forgejo_run_id"] = str(run_id)
            metadata["forgejo_run_id"] = str(run_id)
        if data.get("run_number") is not None:
            st["forgejo_run_number"] = str(data.get("run_number"))
            metadata["forgejo_run_number"] = str(data.get("run_number"))
        if isinstance(data.get("jobs"), list):
            st["forgejo_jobs"] = data["jobs"]

    @staticmethod
    def _parse_kv_output(output: str) -> dict[str, str]:
        data: dict[str, str] = {}
        for line in (output or "").splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key:
                data[key] = value.strip()
        return data

    def _bind_forgejo_run_signal(self, st: dict, block: dict) -> list[LogLine]:
        """Backward-compatible bind signal for older workflows."""
        data = self._parse_kv_output(block.get("output", "") or "")
        run_id = (data.get("forgejo_run_id") or data.get("run_id")
                  or data.get("GITHUB_RUN_ID"))
        if not run_id:
            return [LogLine("forgejo-run bind signal did not include run id", "stderr")]
        st["forgejo_run_id"] = run_id
        st["forgejo_run_number"] = data.get("forgejo_run_number") or data.get("run_number")
        return [LogLine(f"bound Forgejo Actions run_id={run_id} "
                        f"run_number={st.get('forgejo_run_number') or '-'}", "system")]

    async def stream_logs(self, handle: RunHandle) -> AsyncIterator[LogLine]:
        bid = handle.external_id
        st = self._runs[bid]
        yield LogLine(f"plucked {st['comp']} → {st['repo']}/{st['wf']} "
                      f"@ {st.get('ref', 'main')} (build_id={bid})", "system")

        if st.get("forgejo_run_id"):
            yield LogLine(f"Forgejo run_id={st['forgejo_run_id']} "
                          f"run_number={st.get('forgejo_run_number') or '-'}", "system")
        else:
            yield LogLine("Forgejo did not return run metadata; waiting for hub telemetry", "system")

        if st["status"] == RunStatus.FAILED:
            yield LogLine(f"dispatch failed: {st.get('error','unknown')}", "stderr")
            switchboard.release(bid)
            return

        yield LogLine("waiting for Arachne hub telemetry…", "system")

        deadline = time.time() + FORGEJO_DEADLINE
        seen_blocks = 0

        while True:
            got = await switchboard.wait_pulse(bid, timeout=FORGEJO_SILENCE)
            thread = switchboard.get(bid)
            if thread is None:
                st["status"] = RunStatus.FAILED
                yield LogLine("thread lost", "stderr")
                return

            while seen_blocks < len(thread.blocks):
                blk = thread.blocks[seen_blocks]
                seen_blocks += 1
                name = blk.get("step", f"block {seen_blocks}")
                status = blk.get("status", "")

                if name == "forgejo-run":
                    for line in self._bind_forgejo_run_signal(st, blk):
                        yield line
                    continue

                yield LogLine(f"TASK [{name}]", "stdout")
                for ln in (blk.get("output", "") or "").splitlines():
                    yield LogLine(ln)
                marker = "ok" if status in ("ok", "success", "passed") else f"failed: {status}"
                yield LogLine(f"{marker}: [{name}]")

            if thread.final_status is not None:
                if thread.final_status == "success":
                    st["status"] = RunStatus.SUCCESS
                elif thread.final_status == "cancelled":
                    st["status"] = RunStatus.CANCELLED
                else:
                    st["status"] = RunStatus.FAILED
                self._finish(handle, thread)
                yield LogLine(f"thread settled: {thread.final_status}", "system")
                switchboard.release(bid)
                return

            if not got:
                st["status"] = RunStatus.FAILED
                yield LogLine(f"no hub telemetry for {int(FORGEJO_SILENCE)}s — run lost",
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
        """Cut the thread: ask Forgejo to cancel the run, release the switchboard."""
        bid = handle.external_id
        st = self._runs.get(bid, {})
        owner = st.get("owner", FORGEJO_OWNER)
        repo, ext_run = st.get("repo"), st.get("forgejo_run_id")
        cancelled = False
        if repo and ext_run:
            try:
                url = (f"{FORGEJO_URL}/api/v1/repos/{owner}/{repo}"
                       f"/actions/runs/{ext_run}/cancel")
                r = httpx.post(url, headers=self._headers(), timeout=10,
                               verify=VERIFY_TLS)
                cancelled = r.status_code in (200, 202, 204)
            except Exception:  # noqa: BLE001
                cancelled = False
        switchboard.release(bid)
        return cancelled


register_spider(ForgejoSpider())
