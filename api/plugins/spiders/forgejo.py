"""Forgejo v16 BuildSpider.

The spider uses Forgejo's Actions HTTP API end-to-end:
  1. dispatch workflow and bind the returned run id
  2. poll workflow state and logs directly from Forgejo
  3. collect Forgejo Actions artifacts after completion
  4. cancel the workflow through Forgejo's cancel endpoint

No Arachne callback inputs or switchboard telemetry are required.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from io import BytesIO
import os
import re
import time
from typing import AsyncIterator
from urllib.parse import quote, unquote
import zipfile

import httpx

from core.spider import BuildSpider
from core.registry import register_spider
from core.types import RunHandle, LogLine, RunStatus, Artifact, StepSpec


FORGEJO_URL = os.getenv("FORGEJO_URL", "https://forgejo.example.internal").rstrip("/")
FORGEJO_TOKEN = os.getenv("FORGEJO_TOKEN", "")
FORGEJO_OWNER = os.getenv("FORGEJO_OWNER", "example")
NEXUS_URL = os.getenv("NEXUS_URL", "https://nexus.example.internal").rstrip("/")
VERIFY_TLS = os.getenv("FORGEJO_VERIFY_TLS", "true").lower() != "false"

FORGEJO_DEADLINE = float(os.getenv("FORGEJO_DEADLINE", "3600"))
FORGEJO_POLL_INTERVAL = float(os.getenv("FORGEJO_POLL_INTERVAL", "2"))

_NEXUS_URL_RE = re.compile(
    r"(?P<url>https?://[^\s'\"<>]+/repository/(?P<repo>[^/\s'\"<>]+)/(?P<path>[^\s'\"<>]+))",
    re.IGNORECASE,
)
_UPLOADED_RE = re.compile(
    r"uploaded\s+to\s+(?P<repo>[\w.-]+)/(?P<path>[^\s'\"<>]+)",
    re.IGNORECASE,
)
_ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1a\x1c-\x1f\x7f]")
_LOG_TIMESTAMP_RE = re.compile(
    r"^(?P<stamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)\s"
)
_TRAILING_URL_JUNK = "`'\".,;:)]}"

_TERMINAL_SUCCESS = {"success"}
_TERMINAL_CANCELLED = {"cancelled", "canceled"}
_TERMINAL_FAILED = {
    "failure", "failed", "timed_out", "timeout", "action_required",
    "stale", "startup_failure",
}
_TERMINAL_SKIPPED = {"skipped", "neutral"}


class ForgejoSpider(BuildSpider):
    NAME = "forgejo"

    # consumed by the spider; all other keys become workflow_dispatch inputs.
    _CONTROL_KEYS = {"component", "repo", "workflow", "owner", "ref", "branch"}

    def __init__(self):
        self._runs: dict[str, dict] = {}

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"token {FORGEJO_TOKEN}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _api_path(owner: str, repo: str, suffix: str) -> str:
        return f"{FORGEJO_URL}/api/v1/repos/{owner}/{repo}/{suffix.lstrip('/')}"

    @staticmethod
    def _safe_body(body: dict | None) -> dict | None:
        if body is None:
            return None
        safe = dict(body)
        if isinstance(safe.get("inputs"), dict):
            masked = {}
            for key, value in safe["inputs"].items():
                lowered = key.lower()
                masked[key] = "***" if any(
                    marker in lowered for marker in ("token", "secret", "password")
                ) else value
            safe["inputs"] = masked
        return safe

    @classmethod
    def _http_error(
        cls,
        exc: Exception,
        url: str,
        body: dict | None = None,
        method: str = "GET",
    ) -> str:
        safe_body = cls._safe_body(body)
        if isinstance(exc, httpx.HTTPStatusError):
            resp = exc.response
            try:
                detail = resp.json()
            except ValueError:
                detail = resp.text
            return (
                f"Forgejo API {resp.status_code} while {method} {url}: "
                f"{detail!r}; request={safe_body!r}"
            )
        return f"{exc} (while {method} {url}; request={safe_body!r})"

    def healthcheck(self) -> bool:
        try:
            response = httpx.get(
                f"{FORGEJO_URL}/api/v1/version",
                headers=self._headers(),
                timeout=5,
                verify=VERIFY_TLS,
            )
            return response.status_code == 200
        except Exception:
            return False

    @staticmethod
    def _workflow_content_path(workflow: str) -> str:
        if workflow.startswith(".forgejo/workflows/"):
            return workflow
        return f".forgejo/workflows/{workflow}"

    def _preflight_workflow_ref(
        self,
        owner: str,
        repo: str,
        workflow: str,
        ref: str,
    ) -> str | None:
        workflow_path = self._workflow_content_path(workflow)
        encoded_path = quote(workflow_path, safe="/")
        url = self._api_path(owner, repo, f"contents/{encoded_path}")
        try:
            response = httpx.get(
                url,
                headers=self._headers(),
                params={"ref": ref},
                timeout=10,
                verify=VERIFY_TLS,
            )
            response.raise_for_status()
            return None
        except Exception as exc:  # noqa: BLE001
            return self._http_error(exc, url, {"ref": ref}, method="GET")

    def _run_url(self, state: dict, suffix: str = "") -> str:
        base = self._api_path(
            state["owner"],
            state["repo"],
            f"actions/runs/{state['forgejo_run_id']}",
        )
        return f"{base}/{suffix.lstrip('/')}" if suffix else base

    @staticmethod
    def _run_rows(payload: object) -> list[dict]:
        """Accept Forgejo's object, envelope, and bare-list run responses."""
        if isinstance(payload, dict):
            nested = payload.get("workflow_runs")
            if isinstance(nested, list):
                payload = nested
            elif payload.get("id") is not None or payload.get("run_id") is not None:
                return [payload]
            else:
                return []

        if isinstance(payload, list):
            return [
                row for row in payload
                if isinstance(row, dict)
                and (row.get("id") is not None or row.get("run_id") is not None)
            ]
        return []

    @staticmethod
    def _normalized_ref(value: object) -> str:
        ref = str(value or "")
        return ref.removeprefix("refs/heads/")

    @classmethod
    def _select_dispatched_run(
        cls,
        rows: list[dict],
        ref: str,
        started_after: float,
    ) -> dict | None:
        expected_ref = cls._normalized_ref(ref)
        timed: list[tuple[float, dict]] = []
        undated: list[dict] = []

        for row in rows:
            actual_ref = row.get("head_branch") or row.get("ref")
            if (
                actual_ref
                and cls._normalized_ref(actual_ref) != expected_ref
            ):
                continue

            created = row.get("created_at") or row.get("run_started_at")
            if not created:
                undated.append(row)
                continue
            try:
                stamp = datetime.fromisoformat(
                    str(created).replace("Z", "+00:00")
                ).timestamp()
            except (TypeError, ValueError):
                undated.append(row)
                continue
            if stamp >= started_after - 2:
                timed.append((stamp, row))

        if timed:
            timed.sort(key=lambda item: item[0], reverse=True)
            return timed[0][1]
        return undated[0] if undated else None

    def _discover_run(
        self,
        owner: str,
        repo: str,
        workflow: str,
        ref: str,
        started_after: float,
    ) -> dict | None:
        """Find the run when dispatch returned no directly usable metadata."""
        url = self._api_path(owner, repo, f"actions/workflows/{workflow}/runs")
        for _ in range(10):
            try:
                response = httpx.get(
                    url,
                    headers=self._headers(),
                    params={
                        "branch": ref,
                        "event": "workflow_dispatch",
                        "limit": 20,
                    },
                    timeout=10,
                    verify=VERIFY_TLS,
                )
                response.raise_for_status()
                rows = self._run_rows(response.json())
                selected = self._select_dispatched_run(
                    rows, ref, started_after
                )
                if selected:
                    return selected
            except Exception:
                pass
            time.sleep(0.5)
        return None

    def dispatch(self, step: StepSpec, ctx) -> RunHandle:
        w = step.with_
        repo = w.get("repo")
        workflow = w.get("workflow")
        if not repo or not workflow:
            raise KeyError(
                "forgejo spider needs 'repo' and 'workflow' in step.with "
                f"(got repo={repo!r}, workflow={workflow!r})"
            )

        owner = str(w.get("owner") or FORGEJO_OWNER)
        ref = str(w.get("ref") or w.get("branch") or "main")

        preflight_error = self._preflight_workflow_ref(owner, repo, workflow, ref)
        if preflight_error:
            raise RuntimeError(
                f"Forgejo preflight failed for {owner}/{repo}:{ref}/{workflow}: "
                f"{preflight_error}"
            )

        inputs = {
            key: (str(value).lower() if isinstance(value, bool) else str(value))
            for key, value in w.items()
            if key not in self._CONTROL_KEYS
        }

        url = self._api_path(
            owner,
            repo,
            f"actions/workflows/{workflow}/dispatches",
        )
        body = {"ref": ref, "inputs": inputs, "return_run_info": True}
        started_at = time.time()

        try:
            response = httpx.post(
                url,
                headers=self._headers(),
                json=body,
                timeout=15,
                verify=VERIFY_TLS,
            )
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(self._http_error(exc, url, body, method="POST")) from exc

        data: dict = {}
        if response.content:
            try:
                rows = self._run_rows(response.json())
                data = self._select_dispatched_run(
                    rows, ref, started_at
                ) or {}
            except ValueError:
                data = {}

        run_id = data.get("id") or data.get("run_id")
        if not run_id:
            discovered = self._discover_run(
                owner, repo, workflow, ref, started_after=started_at
            )
            if discovered:
                data = discovered
                run_id = data.get("id") or data.get("run_id")

        if not run_id:
            raise RuntimeError(
                "Forgejo accepted workflow dispatch but Arachne could not resolve "
                "the resulting Actions run id"
            )

        key = str(run_id)
        state = {
            "comp": w.get("component", repo),
            "repo": str(repo),
            "owner": owner,
            "workflow": str(workflow),
            "ref": ref,
            "forgejo_run_id": key,
            "forgejo_run_number": data.get("run_number"),
            "status": RunStatus.RUNNING,
            "artifacts": [],
            "last_log_text": "",
            "last_run": data,
            "error": None,
        }
        self._runs[key] = state

        metadata = {
            "repo": state["repo"],
            "workflow": state["workflow"],
            "owner": owner,
            "ref": ref,
            "forgejo_run_id": key,
            "forgejo_run_number": data.get("run_number"),
        }
        return RunHandle(spider=self.NAME, external_id=key, metadata=metadata)

    @staticmethod
    def _map_run_status(payload: dict) -> RunStatus:
        raw = str(payload.get("conclusion") or payload.get("status") or "").lower()
        status = str(payload.get("status") or "").lower()

        if raw in _TERMINAL_SUCCESS:
            return RunStatus.SUCCESS
        if raw in _TERMINAL_CANCELLED:
            return RunStatus.CANCELLED
        if raw in _TERMINAL_FAILED:
            return RunStatus.FAILED
        if raw in _TERMINAL_SKIPPED:
            return RunStatus.SUCCESS

        if status in {"completed"}:
            return RunStatus.FAILED

        if status in {"pending", "queued", "waiting", "requested"}:
            return RunStatus.PENDING
        return RunStatus.RUNNING

    def _fetch_run(self, state: dict) -> dict:
        url = self._run_url(state)
        response = httpx.get(
            url,
            headers=self._headers(),
            timeout=10,
            verify=VERIFY_TLS,
        )
        response.raise_for_status()
        payload = response.json()
        state["last_run"] = payload
        state["status"] = self._map_run_status(payload)
        if state["status"] == RunStatus.FAILED:
            state["error"] = (
                payload.get("conclusion")
                or payload.get("status")
                or "Forgejo Actions run failed"
            )
        return payload

    @staticmethod
    def _decode_log_bytes(data: bytes) -> str:
        """Decode a Forgejo job log without ever interpreting archive bytes as text."""
        if data.startswith(b"\xef\xbb\xbf"):
            data = data[3:]
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("utf-8", errors="replace")

    @staticmethod
    def _normalize_log_text(text: str) -> str:
        """Strip terminal escape/control noise while preserving tabs and newlines."""
        text = _ANSI_ESCAPE_RE.sub("", text or "")
        return _CONTROL_RE.sub("", text).replace("\r\n", "\n").replace("\r", "\n")

    @classmethod
    def _decode_log_response(cls, response: httpx.Response) -> str:
        """Forgejo v16 run logs are ZIP archives; plain text remains supported."""
        data = response.content
        content_type = response.headers.get("content-type", "").lower()
        is_zip = data.startswith(b"PK\x03\x04") or "zip" in content_type

        if not is_zip:
            return cls._normalize_log_text(cls._decode_log_bytes(data))

        chunks: list[str] = []
        with zipfile.ZipFile(BytesIO(data)) as archive:
            names = sorted(
                name for name in archive.namelist()
                if not name.endswith("/") and name.lower().endswith(".log")
            )
            for name in names:
                body = cls._normalize_log_text(cls._decode_log_bytes(archive.read(name)))
                label = name.rsplit("/", 1)[-1]
                chunks.append(f"::group::Forgejo job: {label}")
                chunks.append(body.rstrip("\n"))
                chunks.append("::endgroup::")

        return "\n".join(chunk for chunk in chunks if chunk != "")

    @staticmethod
    def _parse_log_timestamp(line: str) -> float | None:
        match = _LOG_TIMESTAMP_RE.match(line)
        if not match:
            return None
        try:
            return datetime.fromisoformat(
                match.group("stamp").replace("Z", "+00:00")
            ).timestamp()
        except ValueError:
            return None

    @classmethod
    def _group_log_by_steps(cls, text: str, steps: list[dict]) -> str:
        """Insert viewer group commands at Forgejo step start timestamps."""
        timeline: list[tuple[float, int, str]] = []
        for position, step in enumerate(steps):
            started_at = step.get("started_at")
            if not started_at:
                continue
            try:
                started = datetime.fromisoformat(
                    str(started_at).replace("Z", "+00:00")
                ).timestamp()
            except ValueError:
                continue
            number = int(step.get("number") or position + 1)
            name = " ".join(str(step.get("name") or f"step {number}").split())
            timeline.append((started, number, name))

        if not timeline:
            return text

        timeline.sort(key=lambda item: (item[0], item[1]))
        output: list[str] = []
        active = -1
        opened = False

        for line in text.splitlines():
            stamp = cls._parse_log_timestamp(line)
            next_active = active
            if stamp is not None:
                while (
                    next_active + 1 < len(timeline)
                    and timeline[next_active + 1][0] <= stamp
                ):
                    next_active += 1

            if next_active != active:
                if opened:
                    output.append("::endgroup::")
                active = next_active
                if active >= 0:
                    _, number, name = timeline[active]
                    output.append(f"::group::Forgejo step {number}: {name}")
                    opened = True

            output.append(line)

        if opened:
            output.append("::endgroup::")
        return "\n".join(output)

    async def _fetch_jobs(
        self,
        client: httpx.AsyncClient,
        state: dict,
    ) -> list[dict]:
        url = self._run_url(state, "jobs")
        response = await client.get(url)
        if response.status_code in (404, 409):
            return []
        response.raise_for_status()
        payload = response.json()
        jobs = payload.get("jobs", [])
        return jobs if isinstance(jobs, list) else []

    async def _fetch_log_text(self, state: dict) -> str | None:
        run_log_url = self._run_url(state, "logs")
        try:
            async with httpx.AsyncClient(
                headers=self._headers(),
                timeout=15,
                verify=VERIFY_TLS,
                follow_redirects=True,
            ) as client:
                jobs_url = self._run_url(state, "jobs")
                try:
                    jobs = await self._fetch_jobs(client, state)
                except (httpx.HTTPError, ValueError) as exc:
                    state["last_job_log_error"] = self._http_error(
                        exc, jobs_url, method="GET"
                    )
                    jobs = []

                chunks: list[str] = []
                for job in jobs:
                    job_id = job.get("id")
                    if job_id is None:
                        continue
                    job_log_url = self._api_path(
                        state["owner"],
                        state["repo"],
                        f"actions/jobs/{job_id}/logs",
                    )
                    try:
                        response = await client.get(job_log_url)
                        if response.status_code in (404, 409):
                            continue
                        response.raise_for_status()
                        body = self._decode_log_response(response).rstrip("\n")
                    except (
                        httpx.HTTPError,
                        zipfile.BadZipFile,
                        OSError,
                    ) as exc:
                        state["last_job_log_error"] = self._http_error(
                            exc, job_log_url, method="GET"
                        )
                        continue

                    if not body:
                        continue
                    body = self._group_log_by_steps(body, job.get("steps") or [])
                    job_name = " ".join(
                        str(job.get("name") or f"job {job_id}").split()
                    )
                    chunks.extend((
                        f"::group::Forgejo job: {job_name}",
                        body,
                        "::endgroup::",
                    ))

                if chunks:
                    state.pop("last_log_error", None)
                    state.pop("last_job_log_error", None)
                    return "\n".join(chunks)

                response = await client.get(run_log_url)

            if response.status_code in (404, 409):
                return None
            response.raise_for_status()
            return self._decode_log_response(response)
        except (httpx.HTTPError, ValueError, zipfile.BadZipFile, OSError) as exc:
            state["last_log_error"] = self._http_error(
                exc, run_log_url, method="GET"
            )
            return None

    @staticmethod
    def _new_log_lines(previous: str, current: str) -> list[str]:
        if not current:
            return []
        if previous and current.startswith(previous):
            tail = current[len(previous):]
            return tail.splitlines()
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

    async def stream_logs(self, handle: RunHandle) -> AsyncIterator[LogLine]:
        state = self._runs[handle.external_id]
        run_id = state["forgejo_run_id"]
        yield LogLine(
            f"dispatched {state['comp']} → {state['repo']}/{state['workflow']} "
            f"@ {state['ref']} (Forgejo run_id={run_id})",
            "system",
        )

        deadline = time.monotonic() + FORGEJO_DEADLINE

        while True:
            text = await self._fetch_log_text(state)
            if text is not None:
                for line in self._new_log_lines(state["last_log_text"], text):
                    yield LogLine(line)
                state["last_log_text"] = text

            try:
                payload = await asyncio.to_thread(self._fetch_run, state)
            except Exception as exc:  # noqa: BLE001
                state["status"] = RunStatus.FAILED
                state["error"] = self._http_error(
                    exc, self._run_url(state), method="GET"
                )
                yield LogLine(f"Forgejo status polling failed: {state['error']}", "stderr")
                return

            status = state["status"]
            if status in (RunStatus.SUCCESS, RunStatus.FAILED, RunStatus.CANCELLED):
                final_text = await self._fetch_log_text(state)
                if final_text is not None:
                    for line in self._new_log_lines(state["last_log_text"], final_text):
                        yield LogLine(line)
                    state["last_log_text"] = final_text

                await asyncio.to_thread(self._collect_artifacts, state)
                conclusion = payload.get("conclusion") or payload.get("status")
                yield LogLine(
                    f"Forgejo run {run_id} settled: {conclusion or status.value}",
                    "system",
                )
                return

            if time.monotonic() > deadline:
                state["status"] = RunStatus.FAILED
                state["error"] = f"Forgejo run deadline exceeded ({FORGEJO_DEADLINE:.0f}s)"
                yield LogLine(state["error"], "stderr")
                return

            await asyncio.sleep(FORGEJO_POLL_INTERVAL)

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
                name=self._artifact_name(path_clean),
                type="nexus",
                location=f"{repo_clean}/{path_clean}",
                download_url=url_clean,
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

        url = self._run_url(state, "artifacts")
        try:
            response = httpx.get(
                url,
                headers=self._headers(),
                timeout=10,
                verify=VERIFY_TLS,
            )
            response.raise_for_status()
            payload = response.json()
            for item in payload.get("artifacts", []):
                if item.get("expired"):
                    continue
                artifact_id = item.get("id")
                name = str(item.get("name") or f"artifact-{artifact_id}")
                key = f"forgejo:{artifact_id or name}"
                if key in seen:
                    continue
                seen.add(key)
                download_url = (
                    f"{FORGEJO_URL}/{state['owner']}/{state['repo']}"
                    f"/actions/runs/{state['forgejo_run_id']}/artifacts/{quote(name, safe='')}"
                )
                artifacts.append(Artifact(
                    name=name,
                    type="forgejo-actions",
                    location=str(artifact_id or name),
                    download_url=download_url,
                    metadata={
                        "id": artifact_id,
                        "size_in_bytes": item.get("size_in_bytes"),
                        "expired": item.get("expired", False),
                        "archive_download_url": item.get("archive_download_url"),
                    },
                ))
        except Exception as exc:  # noqa: BLE001
            state["artifact_error"] = self._http_error(exc, url, method="GET")

        for artifact in self._nexus_artifacts_from_logs(state.get("last_log_text", "")):
            key = artifact.download_url or artifact.location or artifact.name
            if key in seen:
                continue
            seen.add(key)
            artifacts.append(artifact)

        state["artifacts"] = artifacts

    def get_status(self, handle: RunHandle) -> RunStatus:
        state = self._runs[handle.external_id]
        return state["status"]

    def get_artifacts(self, handle: RunHandle) -> list[Artifact]:
        return list(self._runs[handle.external_id].get("artifacts", []))

    def cancel(self, handle: RunHandle) -> bool:
        state = self._runs.get(handle.external_id)
        if not state:
            return False

        url = self._run_url(state, "cancel")
        try:
            response = httpx.post(
                url,
                headers=self._headers(),
                timeout=10,
                verify=VERIFY_TLS,
            )
            if response.status_code == 409:
                try:
                    self._fetch_run(state)
                except Exception:
                    pass
                return state["status"] in (
                    RunStatus.SUCCESS,
                    RunStatus.FAILED,
                    RunStatus.CANCELLED,
                )
            response.raise_for_status()
            state["status"] = RunStatus.CANCELLED
            return True
        except Exception as exc:  # noqa: BLE001
            state["error"] = self._http_error(exc, url, method="POST")
            return False


register_spider(ForgejoSpider())