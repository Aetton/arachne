"""BuildSpider (Arachne thread → Forgejo).

Pluck model. On dispatch the spider:
  1. plucks a thread on the switchboard → one-time token
  2. POSTs the workflow dispatch, injecting build_id + callback_url + token
     into the workflow inputs
  3. accepts a small bind signal from the runner with Forgejo run metadata
  4. polls Forgejo Actions logs by run_id while the thread is alive
  5. waits for the final thread vibration with status/artifacts

The runner reports back over HTTP to Arachne's callback routes; the switchboard
validates the token (law of the thread) and wakes the waiting driver.
"""
from __future__ import annotations

import io
import os
import time
import zipfile
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

# overall watchdog: max total wait, and max silence between vibrations
FORGEJO_DEADLINE = float(os.getenv("FORGEJO_DEADLINE", "3600"))   # 1h hard cap
FORGEJO_SILENCE = float(os.getenv("FORGEJO_SILENCE", "600"))      # 10m no signal/log
FORGEJO_LOG_POLL = float(os.getenv("FORGEJO_LOG_POLL", "5"))      # poll logs when bound


class ForgejoSpider(BuildSpider):
    NAME = "forgejo"

    # keys consumed by the spider itself — everything else flows to workflow inputs
    _CONTROL_KEYS = {"component", "repo", "workflow", "owner", "ref", "branch"}

    def __init__(self):
        self._runs: dict[str, dict] = {}

    def _headers(self):
        return {"Authorization": f"token {FORGEJO_TOKEN}",
                "Content-Type": "application/json"}

    def _log_headers(self):
        return {"Authorization": f"token {FORGEJO_TOKEN}"}

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

        thread = switchboard.pluck()           # stamp the thread
        build_id = thread.build_id

        # everything that isn't a control key flows to the workflow as inputs
        inputs = {k: (str(v).lower() if isinstance(v, bool) else str(v))
                  for k, v in w.items() if k not in self._CONTROL_KEYS}
        inputs["build_id"] = build_id
        inputs["arachne_callback"] = f"{ARACHNE_URL}/api/threads/{build_id}"
        inputs["arachne_token"] = thread.token

        url = (f"{FORGEJO_URL}/api/v1/repos/{owner}/{repo}"
               f"/actions/workflows/{wf}/dispatches")
        body = {"ref": ref, "inputs": inputs}
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
            "forgejo_job": None,
            "forgejo_workflow": None,
            "forgejo_repository": None,
            "seen_log_lines": {},
            "seen_run_log_lines": 0,
            "jobs_api_missing": False,
            "run_log_error_reported": False,
            "last_log_at": time.time(),
        }
        try:
            r = httpx.post(url, headers=self._headers(), json=body,
                           timeout=10, verify=VERIFY_TLS)
            r.raise_for_status()
            self._runs[build_id]["status"] = RunStatus.RUNNING
        except Exception as exc:  # noqa: BLE001
            err = self._http_error(exc, url, body)
            self._runs[build_id]["status"] = RunStatus.FAILED
            self._runs[build_id]["error"] = err
            metadata["error"] = err

        return RunHandle(spider=self.NAME, external_id=build_id, metadata=metadata)

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

    def _bind_forgejo_run(self, st: dict, block: dict) -> list[LogLine]:
        """Bind Arachne thread to backend Forgejo Actions run metadata."""
        output = block.get("output", "") or ""
        data = self._parse_kv_output(output)
        run_id = (data.get("forgejo_run_id") or data.get("run_id")
                  or data.get("GITHUB_RUN_ID"))
        if not run_id:
            return [LogLine("forgejo-run bind signal did not include run id", "stderr")]

        st["forgejo_run_id"] = run_id
        st["forgejo_run_number"] = data.get("forgejo_run_number") or data.get("run_number")
        st["forgejo_job"] = data.get("forgejo_job") or data.get("job")
        st["forgejo_workflow"] = data.get("forgejo_workflow") or data.get("workflow")
        st["forgejo_repository"] = data.get("forgejo_repository") or data.get("repository")
        st["last_log_at"] = time.time()

        return [
            LogLine(f"bound Forgejo Actions run_id={run_id} "
                    f"run_number={st.get('forgejo_run_number') or '-'}", "system")
        ]

    def _forgejo_get_json(self, url: str) -> dict:
        r = httpx.get(url, headers=self._headers(), timeout=10, verify=VERIFY_TLS)
        r.raise_for_status()
        return r.json()

    def _fetch_run_jobs(self, st: dict) -> list[dict]:
        owner, repo, run_id = st["owner"], st["repo"], st.get("forgejo_run_id")
        if not run_id or st.get("jobs_api_missing"):
            return []
        url = f"{FORGEJO_URL}/api/v1/repos/{owner}/{repo}/actions/runs/{run_id}/jobs"
        try:
            data = self._forgejo_get_json(url)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                st["jobs_api_missing"] = True
                return []
            raise
        jobs = data.get("jobs", data if isinstance(data, list) else [])
        return jobs if isinstance(jobs, list) else []

    @staticmethod
    def _response_to_text(resp: httpx.Response) -> str:
        content_type = resp.headers.get("content-type", "").lower()
        blob = resp.content
        if "zip" in content_type or blob.startswith(b"PK\x03\x04"):
            chunks: list[str] = []
            with zipfile.ZipFile(io.BytesIO(blob)) as archive:
                for name in sorted(archive.namelist()):
                    if name.endswith("/"):
                        continue
                    chunks.append(f"TASK [{name}]")
                    chunks.append(archive.read(name).decode("utf-8", errors="replace"))
            return "\n".join(chunks)
        return resp.text

    def _fetch_run_log_text(self, st: dict) -> str:
        owner, repo, run_id = st["owner"], st["repo"], st.get("forgejo_run_id")
        candidates = [
            f"{FORGEJO_URL}/api/v1/repos/{owner}/{repo}/actions/runs/{run_id}/logs",
            f"{FORGEJO_URL}/api/v1/repos/{owner}/{repo}/actions/runs/{run_id}/attempts/1/logs",
        ]
        errors: list[str] = []
        for url in candidates:
            try:
                r = httpx.get(url, headers=self._log_headers(), timeout=20, verify=VERIFY_TLS)
                if r.status_code == 404:
                    errors.append(f"{url}: 404")
                    continue
                r.raise_for_status()
                return self._response_to_text(r)
            except Exception as exc:  # noqa: BLE001
                errors.append(self._http_error(exc, url, method="GET"))
        if not st.get("run_log_error_reported"):
            st["run_log_error_reported"] = True
            return "[Arachne] could not read Forgejo run log: " + " | ".join(errors)
        return ""

    def _fetch_job_log_text(self, st: dict, job_id: str | int) -> str:
        owner, repo = st["owner"], st["repo"]
        candidates = [
            f"{FORGEJO_URL}/api/v1/repos/{owner}/{repo}/actions/jobs/{job_id}/logs",
            f"{FORGEJO_URL}/api/v1/repos/{owner}/{repo}/actions/runs/{st.get('forgejo_run_id')}/jobs/{job_id}/logs",
        ]
        last_error = ""
        for url in candidates:
            try:
                r = httpx.get(url, headers=self._log_headers(), timeout=20, verify=VERIFY_TLS)
                if r.status_code == 404:
                    last_error = f"{url}: 404"
                    continue
                r.raise_for_status()
                return self._response_to_text(r)
            except Exception as exc:  # noqa: BLE001
                last_error = self._http_error(exc, url, method="GET")
        if last_error:
            return f"[Arachne] could not read Forgejo job log: {last_error}"
        return ""

    def _poll_run_log_fallback(self, st: dict) -> list[LogLine]:
        text = self._fetch_run_log_text(st)
        raw_lines = text.splitlines()
        prev = int(st.get("seen_run_log_lines", 0))
        if prev == 0 and raw_lines:
            lines = [LogLine("TASK [Forgejo run log]", "stdout")]
        else:
            lines = []
        for line in raw_lines[prev:]:
            lines.append(LogLine(line, "stdout"))
        if len(raw_lines) > prev:
            st["seen_run_log_lines"] = len(raw_lines)
            st["last_log_at"] = time.time()
        return lines

    def _poll_forgejo_logs(self, st: dict) -> list[LogLine]:
        if not st.get("forgejo_run_id"):
            return []

        lines: list[LogLine] = []
        try:
            jobs = self._fetch_run_jobs(st)
        except Exception as exc:  # noqa: BLE001
            jobs = []
            if not st.get("run_log_error_reported"):
                lines.append(LogLine(f"Forgejo jobs polling failed, trying run log: {exc}", "system"))

        if not jobs:
            return lines + self._poll_run_log_fallback(st)

        seen = st.setdefault("seen_log_lines", {})
        for job in jobs:
            job_id = job.get("id") or job.get("job_id") or job.get("run_id")
            job_name = job.get("name") or job.get("job_name") or f"job-{job_id}"
            if not job_id:
                continue

            text = self._fetch_job_log_text(st, job_id)
            raw_lines = text.splitlines()
            key = str(job_id)
            prev = int(seen.get(key, 0))
            if prev == 0 and raw_lines:
                lines.append(LogLine(f"TASK [{job_name}]", "stdout"))
            for line in raw_lines[prev:]:
                lines.append(LogLine(line, "stdout"))
            if len(raw_lines) > prev:
                seen[key] = len(raw_lines)
                st["last_log_at"] = time.time()

        return lines

    async def stream_logs(self, handle: RunHandle) -> AsyncIterator[LogLine]:
        bid = handle.external_id
        st = self._runs[bid]
        yield LogLine(f"plucked {st['comp']} → {st['repo']}/{st['wf']} "
                      f"@ {st.get('ref', 'main')} (build_id={bid})", "system")

        if st["status"] == RunStatus.FAILED:
            yield LogLine(f"dispatch failed: {st.get('error','unknown')}", "stderr")
            switchboard.release(bid)
            return

        yield LogLine("waiting for runner to vibrate the thread…", "system")

        deadline = time.time() + FORGEJO_DEADLINE
        seen_blocks = 0

        while True:
            poll_timeout = FORGEJO_LOG_POLL if st.get("forgejo_run_id") else FORGEJO_SILENCE
            got = await switchboard.wait_pulse(bid, timeout=poll_timeout)
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

                if name == "forgejo-run":
                    for line in self._bind_forgejo_run(st, blk):
                        yield line
                    continue

                yield LogLine(f"TASK [{name}]", "stdout")
                for ln in (blk.get("output", "") or "").splitlines():
                    yield LogLine(ln)
                marker = "ok" if status in ("ok", "success", "passed") else f"failed: {status}"
                yield LogLine(f"{marker}: [{name}]")

            if st.get("forgejo_run_id"):
                for line in self._poll_forgejo_logs(st):
                    yield line

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
                last_activity = st.get("last_log_at") or 0
                if not st.get("forgejo_run_id") or (time.time() - last_activity) > FORGEJO_SILENCE:
                    st["status"] = RunStatus.FAILED
                    yield LogLine(f"no vibration/logs for {int(FORGEJO_SILENCE)}s — run lost",
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
