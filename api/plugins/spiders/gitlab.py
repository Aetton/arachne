"""GitLab BuildSpider.

Runs one Arachne build step through GitLab CI using the v4 HTTP API.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from typing import AsyncIterator
from urllib.parse import quote, unquote

import httpx

from core.registry import register_spider
from core.spider import BuildSpider
from core.types import Artifact, LogLine, RunHandle, RunStatus, StepSpec


GITLAB_URL = os.getenv("GITLAB_URL", "https://gitlab.example.internal").rstrip("/")
GITLAB_TOKEN = os.getenv("GITLAB_TOKEN", "")
NEXUS_URL = os.getenv("NEXUS_URL", "https://nexus.example.internal").rstrip("/")
VERIFY_TLS = os.getenv("GITLAB_VERIFY_TLS", "true").lower() != "false"
GITLAB_DEADLINE = float(os.getenv("GITLAB_DEADLINE", "3600"))
GITLAB_POLL_INTERVAL = float(os.getenv("GITLAB_POLL_INTERVAL", "2"))

_ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1a\x1c-\x1f\x7f]")
_NEXUS_URL_RE = re.compile(
    r"(?P<url>https?://[^\s'\"<>]+/repository/(?P<repo>[^/\s'\"<>]+)/(?P<path>[^\s'\"<>]+))",
    re.IGNORECASE,
)
_UPLOADED_RE = re.compile(
    r"uploaded\s+to\s+(?P<repo>[\w.-]+)/(?P<path>[^\s'\"<>]+)",
    re.IGNORECASE,
)
_TRAILING_URL_JUNK = "`'\".,;:)]}"

_PENDING = {"created", "waiting_for_resource", "preparing", "pending", "scheduled", "manual", "blocked"}
_RUNNING = {"running", "canceling"}
_SUCCESS = {"success", "skipped"}
_FAILED = {"failed"}
_CANCELLED = {"canceled", "cancelled"}


class GitLabSpider(BuildSpider):
    NAME = "gitlab"
    _CONTROL_KEYS = {"component", "project", "repo", "ref", "branch"}

    def __init__(self):
        self._runs: dict[str, dict] = {}

    def _headers(self) -> dict[str, str]:
        return {"PRIVATE-TOKEN": GITLAB_TOKEN, "Accept": "application/json"}

    @staticmethod
    def _project_id(project: str) -> str:
        return quote(str(project), safe="")

    @classmethod
    def _project_api(cls, project: str, suffix: str = "") -> str:
        base = f"{GITLAB_URL}/api/v4/projects/{cls._project_id(project)}"
        return f"{base}/{suffix.lstrip('/')}" if suffix else base

    @classmethod
    def _safe_body(cls, body: dict | None) -> dict | None:
        if body is None:
            return None
        safe = dict(body)
        variables = safe.get("variables")
        if isinstance(variables, list):
            masked = []
            for item in variables:
                if not isinstance(item, dict):
                    continue
                row = dict(item)
                key = str(row.get("key") or "").lower()
                if any(marker in key for marker in ("token", "secret", "password", "passwd")):
                    row["value"] = "***"
                masked.append(row)
            safe["variables"] = masked
        return safe

    @classmethod
    def _http_error(cls, exc: Exception, url: str, body: dict | None = None, method: str = "GET") -> str:
        safe_body = cls._safe_body(body)
        if isinstance(exc, httpx.HTTPStatusError):
            response = exc.response
            try:
                detail = response.json()
            except ValueError:
                detail = response.text
            return f"GitLab API {response.status_code} while {method} {url}: {detail!r}; request={safe_body!r}"
        return f"{exc} (while {method} {url}; request={safe_body!r})"

    def healthcheck(self) -> bool:
        try:
            response = httpx.get(
                f"{GITLAB_URL}/api/v4/version",
                headers=self._headers(), timeout=5, verify=VERIFY_TLS,
            )
            return response.status_code == 200
        except Exception:
            return False

    @staticmethod
    def _map_status(value: object) -> RunStatus:
        status = str(value or "").lower()
        if status in _SUCCESS:
            return RunStatus.SUCCESS
        if status in _FAILED:
            return RunStatus.FAILED
        if status in _CANCELLED:
            return RunStatus.CANCELLED
        if status in _PENDING:
            return RunStatus.PENDING
        if status in _RUNNING:
            return RunStatus.RUNNING
        return RunStatus.RUNNING

    def dispatch(self, step: StepSpec, ctx) -> RunHandle:
        w = step.with_
        project = w.get("project") or w.get("repo")
        if not project:
            raise KeyError("gitlab spider needs 'project' (or 'repo') in step.with")
        project = str(project)
        ref = str(w.get("ref") or w.get("branch") or "main")
        variables = [
            {
                "key": str(key),
                "value": str(value).lower() if isinstance(value, bool) else str(value),
            }
            for key, value in w.items()
            if key not in self._CONTROL_KEYS
        ]
        body = {"ref": ref, "variables": variables}
        url = self._project_api(project, "pipeline")
        try:
            response = httpx.post(
                url, headers=self._headers(), json=body, timeout=15, verify=VERIFY_TLS,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(self._http_error(exc, url, body, method="POST")) from exc

        pipeline_id = data.get("id") if isinstance(data, dict) else None
        if pipeline_id is None:
            raise RuntimeError("GitLab created a pipeline but returned no pipeline id")

        key = str(pipeline_id)
        state = {
            "comp": w.get("component", project.rsplit("/", 1)[-1]),
            "project": project,
            "ref": ref,
            "gitlab_pipeline_id": key,
            "status": self._map_status(data.get("status")),
            "last_pipeline": data,
            "job_logs": {},
            "all_log_text": [],
            "artifacts": [],
            "error": None,
        }
        self._runs[key] = state
        return RunHandle(
            spider=self.NAME,
            external_id=key,
            metadata={
                "project": project,
                "ref": ref,
                "gitlab_pipeline_id": key,
                "web_url": data.get("web_url"),
                "sha": data.get("sha"),
            },
        )

    def _pipeline_url(self, state: dict, suffix: str = "") -> str:
        base = self._project_api(state["project"], f"pipelines/{state['gitlab_pipeline_id']}")
        return f"{base}/{suffix.lstrip('/')}" if suffix else base

    def _fetch_pipeline(self, state: dict) -> dict:
        url = self._pipeline_url(state)
        response = httpx.get(url, headers=self._headers(), timeout=10, verify=VERIFY_TLS)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("GitLab pipeline response is not an object")
        state["last_pipeline"] = payload
        state["status"] = self._map_status(payload.get("status"))
        if state["status"] == RunStatus.FAILED:
            state["error"] = str(payload.get("status") or "GitLab pipeline failed")
        return payload

    @staticmethod
    def _normalize_log_text(text: str) -> str:
        text = _ANSI_ESCAPE_RE.sub("", text or "")
        return _CONTROL_RE.sub("", text).replace("\r\n", "\n").replace("\r", "\n")

    @staticmethod
    def _new_log_lines(previous: str, current: str) -> list[str]:
        if not current:
            return []
        if previous and current.startswith(previous):
            return current[len(previous):].splitlines()
        if previous == current:
            return []
        old = previous.splitlines()
        new = current.splitlines()
        common = 0
        for left, right in zip(old, new):
            if left != right:
                break
            common += 1
        return new[common:]

    async def _fetch_jobs(self, client: httpx.AsyncClient, state: dict) -> list[dict]:
        response = await client.get(
            self._pipeline_url(state, "jobs"),
            params={"per_page": 100, "include_retried": "true"},
        )
        response.raise_for_status()
        payload = response.json()
        return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []

    async def _stream_job_updates(self, state: dict) -> AsyncIterator[LogLine]:
        async with httpx.AsyncClient(
            headers=self._headers(), timeout=15, verify=VERIFY_TLS, follow_redirects=True,
        ) as client:
            jobs = await self._fetch_jobs(client, state)
            jobs.sort(key=lambda row: (row.get("created_at") or "", int(row.get("id") or 0)))
            for job in jobs:
                job_id = job.get("id")
                if job_id is None:
                    continue
                job_key = str(job_id)
                trace_url = self._project_api(state["project"], f"jobs/{job_key}/trace")
                try:
                    response = await client.get(trace_url)
                    if response.status_code == 404:
                        continue
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    state["last_log_error"] = self._http_error(exc, trace_url, method="GET")
                    continue

                current = self._normalize_log_text(response.text)
                previous = state["job_logs"].get(job_key, "")
                lines = self._new_log_lines(previous, current)
                state["job_logs"][job_key] = current
                if not lines:
                    continue

                name = " ".join(str(job.get("name") or f"job {job_key}").split())
                stage = " ".join(str(job.get("stage") or "").split())
                label = f"{stage} / {name}" if stage else name
                yield LogLine(f"::group::GitLab job: {label}", "system")
                for line in lines:
                    state["all_log_text"].append(line)
                    yield LogLine(line)
                yield LogLine("::endgroup::", "system")

    async def stream_logs(self, handle: RunHandle) -> AsyncIterator[LogLine]:
        state = self._runs[handle.external_id]
        pipeline_id = state["gitlab_pipeline_id"]
        yield LogLine(
            f"dispatched {state['comp']} → {state['project']} @ {state['ref']} "
            f"(GitLab pipeline_id={pipeline_id})",
            "system",
        )
        deadline = time.monotonic() + GITLAB_DEADLINE
        while True:
            try:
                async for line in self._stream_job_updates(state):
                    yield line
            except Exception as exc:  # noqa: BLE001
                state["last_log_error"] = str(exc)

            try:
                payload = await asyncio.to_thread(self._fetch_pipeline, state)
            except Exception as exc:  # noqa: BLE001
                state["status"] = RunStatus.FAILED
                state["error"] = self._http_error(exc, self._pipeline_url(state), method="GET")
                yield LogLine(f"GitLab status polling failed: {state['error']}", "stderr")
                return

            if state["status"].is_terminal:
                try:
                    async for line in self._stream_job_updates(state):
                        yield line
                except Exception:
                    pass
                await asyncio.to_thread(self._collect_artifacts, state)
                yield LogLine(
                    f"GitLab pipeline {pipeline_id} settled: {payload.get('status') or state['status'].value}",
                    "system",
                )
                return

            if time.monotonic() > deadline:
                state["status"] = RunStatus.FAILED
                state["error"] = f"GitLab pipeline deadline exceeded ({GITLAB_DEADLINE:.0f}s)"
                yield LogLine(state["error"], "stderr")
                return
            await asyncio.sleep(GITLAB_POLL_INTERVAL)

    def _fetch_jobs_sync(self, state: dict) -> list[dict]:
        response = httpx.get(
            self._pipeline_url(state, "jobs"), headers=self._headers(),
            params={"per_page": 100, "include_retried": "true"}, timeout=15, verify=VERIFY_TLS,
        )
        response.raise_for_status()
        payload = response.json()
        return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []

    @staticmethod
    def _clean_artifact_path(value: str) -> str:
        return unquote(str(value or "").strip().rstrip(_TRAILING_URL_JUNK))

    @staticmethod
    def _artifact_name(path: str) -> str:
        return path.rsplit("/", 1)[-1] or "artifact"

    def _nexus_artifacts_from_logs(self, text: str) -> list[Artifact]:
        found: list[Artifact] = []
        seen: set[str] = set()
        text = self._normalize_log_text(text)

        def add(repo: str, path: str, download_url: str) -> None:
            repo_clean = self._clean_artifact_path(repo)
            path_clean = self._clean_artifact_path(path)
            url_clean = self._clean_artifact_path(download_url)
            if not repo_clean or not path_clean or not url_clean or url_clean in seen:
                return
            seen.add(url_clean)
            found.append(Artifact(
                name=self._artifact_name(path_clean), type="nexus",
                location=f"{repo_clean}/{path_clean}", download_url=url_clean,
                metadata={"repo": repo_clean, "path": path_clean},
            ))

        for match in _NEXUS_URL_RE.finditer(text or ""):
            add(match.group("repo"), match.group("path"), match.group("url"))
        for match in _UPLOADED_RE.finditer(text or ""):
            repo = match.group("repo")
            path = match.group("path")
            add(repo, path, f"{NEXUS_URL}/repository/{repo}/{path}")
        return found

    def _collect_artifacts(self, state: dict) -> None:
        artifacts: list[Artifact] = []
        seen: set[str] = set()
        try:
            for job in self._fetch_jobs_sync(state):
                job_id = job.get("id")
                artifact_file = job.get("artifacts_file")
                if job_id is None or not isinstance(artifact_file, dict):
                    continue
                filename = artifact_file.get("filename")
                if not filename:
                    continue
                key = f"gitlab:{job_id}"
                if key in seen:
                    continue
                seen.add(key)
                artifacts.append(Artifact(
                    name=str(filename), type="gitlab-job-artifacts", location=str(job_id),
                    download_url=self._project_api(state["project"], f"jobs/{job_id}/artifacts"),
                    metadata={
                        "job_id": job_id, "job_name": job.get("name"),
                        "stage": job.get("stage"), "size": artifact_file.get("size"),
                    },
                ))
        except Exception as exc:  # noqa: BLE001
            state["artifact_error"] = str(exc)

        for artifact in self._nexus_artifacts_from_logs("\n".join(state.get("all_log_text", []))):
            key = artifact.download_url or artifact.location or artifact.name
            if key in seen:
                continue
            seen.add(key)
            artifacts.append(artifact)
        state["artifacts"] = artifacts

    def get_status(self, handle: RunHandle) -> RunStatus:
        return self._runs[handle.external_id]["status"]

    def get_artifacts(self, handle: RunHandle) -> list[Artifact]:
        return list(self._runs[handle.external_id].get("artifacts", []))

    def cancel(self, handle: RunHandle) -> bool:
        state = self._runs.get(handle.external_id)
        if not state:
            return False
        url = self._pipeline_url(state, "cancel")
        try:
            response = httpx.post(url, headers=self._headers(), timeout=10, verify=VERIFY_TLS)
            response.raise_for_status()
            payload = response.json() if response.content else {}
            if isinstance(payload, dict):
                state["last_pipeline"] = payload
                state["status"] = self._map_status(payload.get("status"))
            if not state["status"].is_terminal:
                state["status"] = RunStatus.CANCELLED
            return True
        except Exception as exc:  # noqa: BLE001
            state["error"] = self._http_error(exc, url, method="POST")
            return False


register_spider(GitLabSpider())
