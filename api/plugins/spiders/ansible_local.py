"""CommandSpider: runs ansible-playbook locally against explicit targets.

Playbooks normally come from a Git-backed PlaybookRepository configured in the
Arachne control panel. Brood targets are converted into an ephemeral Ansible
inventory at runtime. Their credentials are resolved through Control -> Secrets
and never placed on the ansible-playbook command line.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import tempfile
from typing import AsyncIterator

from core.brood import (
    command_target_vars,
    is_brood_target,
    preferred_endpoint,
    validate_brood_target,
)
from core.playbook_repository import PlaybookRepository, ResolvedPlaybook
from core.spider import CommandSpider
from core.registry import register_spider
from core.types import RunHandle, LogLine, RunStatus, Artifact, RunOutput, StepSpec
from playbook_settings import get_settings
from secrets_store import resolve_credential

LOCAL_PLAYBOOKS_DIR = os.getenv("ANSIBLE_PLAYBOOKS_DIR", "../playbooks")
NEXUS_URL = os.getenv("NEXUS_URL", "https://nexus.redsoft.internal").rstrip("/")

_ART = re.compile(r"uploaded to (?P<repo>[\w\-]+)/(?P<path>\S+)")
_SENSITIVE = ("token", "secret", "password", "private_key")
_CONTROL_PARAMS = {"playbook", "playbook_ref"}
_SAFE_INVENTORY_NAME = re.compile(r"[^A-Za-z0-9_.-]+")


def _local_playbooks_dir() -> str:
    for candidate in [
        LOCAL_PLAYBOOKS_DIR,
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "playbooks"),
        "playbooks",
    ]:
        if os.path.isdir(candidate):
            return candidate
    return LOCAL_PLAYBOOKS_DIR


def _scalar(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _artifact_vars(key: str, artifact: Artifact) -> list[tuple[str, str]]:
    if is_brood_target(artifact):
        return [
            (name, value)
            for name, value in command_target_vars(key, artifact)
            if not name.endswith("_credentials_ref")
        ]
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
    for key, value in params.items():
        if key in _CONTROL_PARAMS:
            continue
        if isinstance(value, Artifact):
            for var_key, var_value in _artifact_vars(key, value):
                out += ["-e", f"{var_key}={var_value}"]
            continue
        if isinstance(value, (str, int, float, bool)):
            out += ["-e", f"{key}={_scalar(value)}"]
    return out


def _output_params(params: dict) -> dict:
    out = {}
    for key, value in params.items():
        if key in _CONTROL_PARAMS:
            continue
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


def _local_resolution(playbook: str) -> ResolvedPlaybook:
    root = os.path.realpath(_local_playbooks_dir())
    path = os.path.realpath(os.path.join(root, playbook))
    if os.path.commonpath([root, path]) != root:
        raise ValueError(f"unsafe local playbook path: {playbook!r}")
    return ResolvedPlaybook(
        path=path,
        repo="local",
        ref="local",
        sha="",
        relative_path=playbook,
    )


def _configured_repository() -> PlaybookRepository | None:
    settings = get_settings()
    repo_url = settings.get("repo_url", "").strip()
    if not repo_url:
        return None
    return PlaybookRepository(
        repo_url,
        default_ref=settings.get("default_ref", "main"),
        subdir=settings.get("subdir", "playbooks"),
        cache_dir=settings.get("cache_dir", "/var/cache/arachne/playbooks"),
        credentials_ref=settings.get("credentials_ref", ""),
    )


def _brood_targets(params: dict) -> list[tuple[str, Artifact]]:
    return [
        (str(key), value)
        for key, value in params.items()
        if isinstance(value, Artifact) and is_brood_target(value)
    ]


def _inventory_name(key: str, artifact: Artifact, used: set[str]) -> str:
    base = _SAFE_INVENTORY_NAME.sub("-", key).strip("-.") or "target"
    candidate = base
    index = 2
    while candidate in used:
        candidate = f"{base}-{index}"
        index += 1
    used.add(candidate)
    return candidate


def _write_private_file(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
        if content and not content.endswith("\n"):
            fh.write("\n")
    os.chmod(path, 0o600)


def _target_inventory_vars(
    key: str,
    artifact: Artifact,
    runtime_dir: str,
) -> dict[str, object]:
    md = validate_brood_target(artifact)
    endpoint = preferred_endpoint(artifact)
    protocol = str(endpoint["protocol"]).lower()
    access = md["access"]
    secret_ref = access.get("credentials") or {}
    credential_slug = (
        str(secret_ref.get("ref") or "").strip()
        if isinstance(secret_ref, dict) and secret_ref.get("type") == "secret_ref"
        else ""
    )
    if not credential_slug:
        raise RuntimeError(
            f"Brood target {artifact.name!r} has no credentials_ref for {protocol} access"
        )

    credential = resolve_credential(credential_slug)
    if credential.kind != protocol:
        raise RuntimeError(
            f"Brood target {artifact.name!r} uses {protocol}, but credential "
            f"{credential.slug!r} has type {credential.kind!r}"
        )
    if not credential.username:
        raise RuntimeError(f"credential {credential.slug!r} has no username")

    host_vars: dict[str, object] = {
        "ansible_host": str(endpoint["host"]),
        "ansible_port": int(endpoint["port"]),
        "ansible_user": credential.username,
        "ansible_connection": protocol,
    }

    if protocol == "ssh":
        private_key = str(credential.values.get("private_key") or "")
        password = str(credential.values.get("password") or "")
        if private_key:
            key_path = os.path.join(runtime_dir, f"{key}.key")
            _write_private_file(key_path, private_key)
            host_vars["ansible_ssh_private_key_file"] = key_path
        elif password:
            host_vars["ansible_password"] = password
        else:
            raise RuntimeError(
                f"SSH credential {credential.slug!r} has neither private_key nor password"
            )

        known_hosts = str(credential.values.get("known_hosts") or "")
        known_hosts_path = os.path.join(runtime_dir, f"{key}.known_hosts")
        _write_private_file(known_hosts_path, known_hosts)
        strict = "yes" if known_hosts else "accept-new"
        host_vars["ansible_ssh_common_args"] = (
            f"-o StrictHostKeyChecking={strict} "
            f"-o UserKnownHostsFile={known_hosts_path}"
        )
        return host_vars

    if protocol == "winrm":
        password = str(credential.values.get("password") or "")
        if not password:
            raise RuntimeError(f"WinRM credential {credential.slug!r} has no password")
        host_vars["ansible_password"] = password
        transport = str(credential.metadata.get("transport") or "").strip()
        cert_validation = str(
            credential.metadata.get("server_cert_validation") or ""
        ).strip()
        if transport:
            host_vars["ansible_winrm_transport"] = transport
        if cert_validation:
            host_vars["ansible_winrm_server_cert_validation"] = cert_validation
        return host_vars

    raise RuntimeError(f"unsupported Brood access protocol for ansible-local: {protocol}")


def _prepare_runtime_inventory(params: dict) -> tuple[str | None, str | None, int]:
    targets = _brood_targets(params)
    if not targets:
        return None, None, 0

    runtime_dir = tempfile.mkdtemp(prefix="arachne-ansible-")
    os.chmod(runtime_dir, 0o700)
    try:
        hosts = {}
        used: set[str] = set()
        for key, artifact in targets:
            name = _inventory_name(key, artifact, used)
            hosts[name] = _target_inventory_vars(name, artifact, runtime_dir)

        inventory = {"all": {"hosts": hosts}}
        inventory_path = os.path.join(runtime_dir, "inventory.yml")
        _write_private_file(
            inventory_path,
            json.dumps(inventory, ensure_ascii=False, indent=2),
        )
        return runtime_dir, inventory_path, len(hosts)
    except Exception:
        shutil.rmtree(runtime_dir, ignore_errors=True)
        raise


class AnsibleLocalSpider(CommandSpider):
    NAME = "ansible-local"

    def __init__(self):
        self._runs: dict[str, dict] = {}

    def _resolve_playbook(self, playbook: str, ref: str | None) -> ResolvedPlaybook:
        repository = _configured_repository()
        if repository is not None:
            return repository.resolve(playbook, ref=ref)
        return _local_resolution(playbook)

    def _base_command(self, resolved: ResolvedPlaybook, params: dict) -> list[str]:
        if shutil.which("ansible-playbook") and os.path.exists(resolved.path):
            return ["ansible-playbook", resolved.path, *_extra_vars(params)]
        demo = os.path.join(
            os.path.dirname(__file__), "..", "..", "runners", "demo_play.sh"
        )
        return ["bash", demo, params.get("component", resolved.relative_path)]

    def dispatch(self, step: StepSpec, ctx) -> RunHandle:
        playbook = step.with_.get("playbook") or f"build-{step.with_.get('component','x')}.yml"
        playbook_ref = step.with_.get("playbook_ref")
        resolved = self._resolve_playbook(
            str(playbook),
            str(playbook_ref) if playbook_ref else None,
        )
        cmd = self._base_command(resolved, step.with_)
        ext = f"{step.id}-{id(self):x}"
        self._runs[ext] = {
            "cmd": cmd,
            "playbook": playbook,
            "playbook_source": resolved,
            "runner": "ansible-playbook" if cmd and cmd[0] == "ansible-playbook" else "demo",
            "lines": [],
            "status": RunStatus.PENDING,
            "artifacts": [],
            "params": step.with_,
            "runtime_dir": None,
            "target_count": len(_brood_targets(step.with_)),
        }
        return RunHandle(
            spider=self.NAME,
            external_id=ext,
            metadata={
                "playbook_repo": resolved.repo,
                "playbook_ref": resolved.ref,
                "playbook_sha": resolved.sha,
                "playbook_path": resolved.relative_path,
                "target_count": len(_brood_targets(step.with_)),
            },
        )

    async def stream_logs(self, handle: RunHandle) -> AsyncIterator[LogLine]:
        st = self._runs[handle.external_id]
        source = st["playbook_source"]
        st["status"] = RunStatus.RUNNING
        runtime_dir = None
        try:
            cmd = list(st["cmd"])
            if cmd and cmd[0] == "ansible-playbook":
                runtime_dir, inventory_path, target_count = _prepare_runtime_inventory(st["params"])
                st["runtime_dir"] = runtime_dir
                st["target_count"] = target_count
                if inventory_path:
                    cmd[2:2] = ["-i", inventory_path]

            if source.repo != "local":
                yield LogLine(
                    f"playbook: {source.relative_path} @ {source.ref} ({source.sha[:12]})",
                    "system",
                )
            if st["target_count"]:
                yield LogLine(
                    f"inventory: {st['target_count']} Brood target(s), credentials resolved through Secrets",
                    "system",
                )

            display_cmd = ["<runtime-inventory>" if item.endswith("/inventory.yml") else item for item in cmd]
            yield LogLine(f"$ {' '.join(display_cmd)}", "system")

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env={
                    **os.environ,
                    "ANSIBLE_FORCE_COLOR": "0",
                    "PYTHONUNBUFFERED": "1",
                },
            )
            st["proc"] = proc
            assert proc.stdout is not None
            async for raw in proc.stdout:
                line = raw.decode(errors="replace").rstrip("\n")
                st["lines"].append(line)
                match = _ART.search(line)
                if match:
                    repo, path = match.group("repo"), match.group("path")
                    st["artifacts"].append(
                        Artifact(
                            name=path.rsplit("/", 1)[-1],
                            type="nexus",
                            location=f"{repo}/{path}",
                            download_url=f"{NEXUS_URL}/repository/{repo}/{path}",
                            metadata={"repo": repo, "path": path},
                        )
                    )
                yield LogLine(line)
            await proc.wait()
            st["status"] = RunStatus.SUCCESS if proc.returncode == 0 else RunStatus.FAILED
        except Exception as exc:
            st["status"] = RunStatus.FAILED
            st["error"] = str(exc)
            yield LogLine(f"Ansible runtime preparation failed: {exc}", "stderr")
        finally:
            st["runtime_dir"] = None
            if runtime_dir:
                shutil.rmtree(runtime_dir, ignore_errors=True)

    def get_status(self, handle: RunHandle) -> RunStatus:
        return self._runs[handle.external_id]["status"]

    def get_artifacts(self, handle: RunHandle) -> list[Artifact]:
        return self._runs[handle.external_id]["artifacts"]

    def get_outputs(self, handle: RunHandle) -> list[RunOutput]:
        st = self._runs[handle.external_id]
        source = st["playbook_source"]
        return [
            RunOutput(
                kind="ansible",
                title=st["playbook"],
                data={
                    "status": st["status"].value,
                    "runner": st["runner"],
                    "repository": source.repo,
                    "ref": source.ref,
                    "sha": source.sha,
                    "path": source.relative_path,
                    "targets": st.get("target_count", 0),
                    "params": _output_params(st["params"]),
                },
            )
        ]

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
