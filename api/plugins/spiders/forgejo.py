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
import re
import time
from typing import AsyncIterator
from urllib.parse import quote, unquote, urlparse

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

_NEXUS_URL_RE = re.compile(
    r"(?P<url>https?://[^\s'\"<>]+/repository/(?P<repo>[^/\s'\"<>]+)/(?P<path>[^\s'\"<>]+))",
    re.IGNORECASE,
)
_UPLOADED_RE = re.compile(
    r"uploaded\s+to\s+(?P<repo>[\w.-]+)\/(?P<path>[^\s'\"<>]+)",
    re.IGNORECASE,
)
_TRAILING_URL_JUNK = "`'\".,;:)]}"
_UPLOAD_STEP_HINTS = ("upload", "publish", "artifact", "nexus")


class ForgejoSpider(BuildSpider):
    NAME = "forgejo"

    # keys consumed by the spider itself — everything else flows to workflow inputs
    _CONTROL_KEYS = {"component", "repo", "workflow", "owner", "ref", "branch"}
    _SECRET_INPUT_KEYS = {"arachne_token", "token", "password", "secret"}

    def __init__(self):
        self._runs: dict[str, dict] = {}

    def _headers(self):
        return {"Authorization": f"token {FORGEJO_TOKEN}",
                "Content-Type": "application/json"}

    @classmethod
    def _safe_body(cls, body: dict | None) -> dict | None:
        if body is None:
            return None
        safe = dict(body)
        inputs = safe.get("inputs")
        if isinstance(inputs, dict):
            masked_inputs = dict(inputs)
            for key in list(masked_inputs):
                if key.lower() in cls._SECRET_INPUT_KEYS:
                    masked_inputs[key] = "***"
            safe["inputs"] = masked_inputs
        return safe

    @classmethod
    def _http_error(cls, exc: Exception, url: str, body: dict | None = None,
                    method: str = "POST") -> str:
        """Return an operator-readable backend error, including Forgejo's body."""
        safe_body = cls._safe_body(body)
        if isinstance(exc, httpx.HTTPStatusError):
            resp = exc.response
            try:
                detail = resp.json()
            except ValueError:
                detail = resp.text
            return (f"Forgejo API {resp.status_code} while {method} {url}: {detail!r}; "
                    f"request={safe_body!r}")
        return f"{exc} (while {method} {url}; request={safe_body!r})"

    def healthcheck(self) -> bool:
        try:
            r = httpx.get(f"{FORGEJO_URL}/api/v1/version",
                          headers=self._headers(), timeout=5, verify=VERIFY_TLS)
            return r.status_code == 200
        except Exception:
            return False

    @staticmethod
    def _workflow_content_path(workflow: str) -> str:
        if workflow.startswith(".forgejo/workflows/"):
            return workflow
        return f".forgejo/workflows/{workflow}"

    def _preflight_workflow_ref(self, owner: str, repo: str, workflow: str, ref: str) -> str | None:
        workflow_path = self._workflow_content_path(workflow)
        encoded_path = quote(workflow_path, safe="/")
        url = f"{FORGEJO_URL}/api/v1/repos/{owner}/{repo}/contents/{encoded_path}"
        try:
            r = httpx.get(url, headers=self._headers(), params={"ref": ref},
                          timeout=10, verify=VERIFY_TLS)
            r.raise_for_status()
            return None
        except Exception as exc:  # noqa: BLE001
            return self._http_error(exc, url, {"ref": ref}, method="GET")

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

        preflight_error = self._preflight_workflow_ref(owner, repo, wf, ref)
        if preflight_error:
            err = f"Forgejo preflight failed for {owner}/{repo}:{ref}/{wf}: {preflight_error}"
            self._runs[build_id]["status"] = RunStatus.FAILED
            self._runs[build_id]["error"] = err
            metadata["error"] = err
            return RunHandle(spider=self.NAME, external_id=build_id, metadata=metadata)

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

        if st["status"] == RunStatus.FAILED:
            yield LogLine(f"dispatch failed: {st.get('error','unknown')}", "stderr")
            switchboard.release(bid)
            return

        if st.get("forgejo_run_id"):
            yield LogLine(f"Forgejo run_id={st['forgejo_run_id']} "
                          f"run_number={st.get('forgejo_run_number') or '-'}", "system")
        else:
            yield LogLine("Forgejo did not return run metadata; waiting for hub telemetry", "system")

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

    @staticmethod
    def _clean_artifact_path(value: str) -> str:
        return unquote(str(value or "").strip().rstrip(_TRAILING_URL_JUNK))

    @staticmethod
    def _artifact_name(path: str) -> str:
        return path.rsplit("/", 1)[-1] or "artifact"

    @staticmethod
    def _is_upload_block(block: dict) -> bool:
        step = str(block.get("step") or "").lower()
        output = str(block.get("output") or "").lower()
        return any(hint in step for hint in _UPLOAD_STEP_HINTS) or "--upload-file" in output

    def _artifact_from_nexus_url(self, url: str, source_step: str = "") -> dict | None:
        cleaned = self._clean_artifact_path(url)
        parsed = urlparse(cleaned)
        marker = "/repository/"
        if marker not in parsed.path:
            return None
        repo_path = parsed.path.split(marker, 1)[1]
        if "/" not in repo_path:
            return None
        repo, path = repo_path.split("/", 1)
        repo = self._clean_artifact_path(repo)
        path = self._clean_artifact_path(path)
        if not repo or not path:
            return None
        return {
            "name": self._artifact_name(path),
            "type": "nexus",
            "location": f"{repo}/{path}",
            "download_url": cleaned,
            "metadata": {"repo": repo, "path": path, "source_step": source_step},
        }

    def _artifact_from_uploaded_line(self, repo: str, path: str, source_step: str = "") -> dict | None:
        repo = self._clean_artifact_path(repo)
        path = self._clean_artifact_path(path)
        if not repo or not path:
            return None
        return {
            "name": self._artifact_name(path),
            "type": "nexus",
            "location": f"{repo}/{path}",
            "download_url": f"{NEXUS_URL}/repository/{repo}/{path}",
            "metadata": {"repo": repo, "path": path, "source_step": source_step},
        }

    def _artifacts_from_block_list(self, blocks: list[dict]) -> list[dict]:
        found: list[dict] = []
        seen: set[str] = set()

        def add(artifact: dict | None) -> None:
            if not artifact:
                return
            key = artifact.get("download_url") or artifact.get("location") or artifact.get("name")
            if not key or key in seen:
                return
            seen.add(key)
            found.append(artifact)

        for block in blocks:
            output = block.get("output", "") or ""
            source_step = str(block.get("step") or "")
            for match in _NEXUS_URL_RE.finditer(output):
                add(self._artifact_from_nexus_url(match.group("url"), source_step))
            for match in _UPLOADED_RE.finditer(output):
                add(self._artifact_from_uploaded_line(
                    match.group("repo"), match.group("path"), source_step))
        return found

    def _artifacts_from_blocks(self, thread) -> list[dict]:
        """Recover Nexus artifacts from wrapper-captured upload logs.

        Old workflows posted `artifacts` explicitly in the final status. The shell
        wrapper settles the thread from a post hook, so forgotten artifact JSON
        files used to make us fall back to a fake `<component>.tar.gz`. Instead,
        read the mirrored upload output and recover Nexus links deterministically.
        """
        blocks = list(getattr(thread, "blocks", []) or [])
        upload_blocks = [block for block in blocks if self._is_upload_block(block)]
        if upload_blocks:
            artifacts = self._artifacts_from_block_list(upload_blocks)
            if artifacts:
                return artifacts
        return self._artifacts_from_block_list(blocks)

    def _finish(self, handle: RunHandle, thread):
        st = self._runs[handle.external_id]
        raw_artifacts = thread.artifacts or self._artifacts_from_blocks(thread)
        st["artifacts"] = [
            Artifact(name=a.get("name", "artifact"),
                     type=a.get("type", "nexus"),
                     location=a.get("location", ""),
                     download_url=a.get("download_url"),
                     metadata=a.get("metadata", {}))
            for a in raw_artifacts
        ]

    def get_status(self, handle: RunHandle) -> RunStatus:
        return self._runs[handle.external_id]["status"]

    def get_artifacts(self, handle: RunHandle) -> list[Artifact]:
        return self._runs[handle.external_id]["artifacts"]

    def cancel(self, handle: RunHandle) -> bool:
        st = self._runs.get(handle.external_id)
        if not st:
            return False
        st["status"] = RunStatus.CANCELLED
        switchboard.release(handle.external_id)
        return True


register_spider(ForgejoSpider())
