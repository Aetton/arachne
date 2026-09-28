"""Shared OpenTofu process, state and Brood lifecycle runtime."""

from __future__ import annotations
import asyncio
import fcntl
import json
import os
import re
import shutil
import signal
import uuid
from pathlib import Path
from typing import AsyncIterator
from core.lifetime import normalize_lifetime
from core.spider import ProvisionSpider
from core.types import Artifact, LogLine, RunHandle, RunStatus, StepSpec

CONN_BY_OS = {"redos7": ("ssh", 22), "redos8": ("ssh", 22), "windows": ("winrm", 5985)}
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")
_TRUE = {"1", "true", "yes", "on"}


class TofuSpider(ProvisionSpider):
    SUPPORTS_DESTROY = True
    PRESERVE_CANCEL_ARTIFACTS = True
    MODULE = "stand"
    NAME = "abstract-tofu"

    def __init__(self):
        self._runs: dict[str, dict] = {}

    def _tofu_dir(self) -> Path:
        for candidate in [
            Path(os.getenv("TOFU_ROOT", "../tofu")) / self.MODULE,
            Path(__file__).resolve().parents[2] / "tofu" / self.MODULE,
        ]:
            if candidate.is_dir():
                return candidate.resolve()
        return (Path(os.getenv("TOFU_ROOT", "../tofu")) / self.MODULE).resolve()

    def _dev_fallback_enabled(self) -> bool:
        return (
            self.NAME == "tofu-proxmox"
            and os.getenv("TOFU_DEV_FALLBACK", "false").strip().lower() in _TRUE
        )

    @staticmethod
    def _validate_name(name: str) -> None:
        if not _NAME_RE.fullmatch(name):
            raise ValueError(
                "Stand name must start with an alphanumeric character and contain "
                "only letters, digits, '.', '_' or '-' (max 63 chars)"
            )

    @staticmethod
    def _positive_int(value, *, field: str) -> int | None:
        if value in (None, ""):
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"resources.{field} must be an integer") from exc
        if parsed <= 0:
            raise ValueError(f"resources.{field} must be greater than zero")
        return parsed

    def _state_dir(self, name: str, connection: str = "") -> Path:
        root = (
            Path(os.getenv("TOFU_STATE_ROOT", "/tmp/arachne-tofu-state"))
            .expanduser()
            .resolve()
        )
        self._validate_name(name)
        if connection:
            if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", connection):
                raise ValueError("Invalid connection key")
            return root / self.NAME / connection / name
        return root / name  # Preserve legacy Proxmox states.

    def _prepare_workdir(
        self, name: str, source_dir: Path, connection: str = ""
    ) -> tuple[Path, Path]:
        state_dir = self._state_dir(name, connection)
        work_dir = state_dir / "module"
        work_dir.mkdir(parents=True, exist_ok=True)
        # A previously destroyed stand may have used a different module revision.
        for pattern in ("*.tf", "*.tf.json"):
            for old in work_dir.glob(pattern):
                old.unlink()

        copied = False
        for pattern in ("*.tf", "*.tf.json"):
            for src in source_dir.glob(pattern):
                shutil.copy2(src, work_dir / src.name)
                copied = True

        (work_dir / ".terraform.lock.hcl").unlink(missing_ok=True)
        source_lock = source_dir / ".terraform.lock.hcl"
        if source_lock.exists():
            shutil.copy2(source_lock, work_dir / source_lock.name)

        if not copied:
            raise ValueError(f"No OpenTofu configuration files found in {source_dir}")
        return work_dir, state_dir / "terraform.tfstate"

    @staticmethod
    def _tofu_env(work_dir: Path) -> dict[str, str]:
        env = os.environ.copy()
        # Never leak another infrastructure provider's credentials to a child.
        for key in list(env):
            if key.startswith("TF_VAR_ovirt_") or key in {
                "PROXMOX_VE_USERNAME",
                "PROXMOX_VE_PASSWORD",
                "PROXMOX_VE_OTP",
            }:
                env.pop(key)
        env["TF_DATA_DIR"] = str(work_dir / ".terraform")
        return env

    def dispatch(self, step: StepSpec, ctx) -> RunHandle:
        name = str(step.with_.get("name", "test-stand"))
        raw_action = (step.action or "brood").strip().lower()
        action = "provision" if raw_action in {"brood", "provision"} else raw_action
        self._validate_name(name)
        if action not in {"provision", "destroy"}:
            raise ValueError(
                f"Unsupported {self.NAME} action {raw_action!r}; use brood or destroy"
            )

        backend = self._resolve_backend(step.with_, action=action, name=name)
        vm_os = backend["os"]
        resources = (
            self._resources(step.with_, backend["template"])
            if action == "provision"
            else {
                "cpu": None,
                "memory_gb": None,
                "memory_mb": None,
                "disk_gb": None,
                "disk_interface": "",
                "disk_datastore": "",
            }
        )
        lifetime = (
            normalize_lifetime(step.with_.get("lifetime"))
            if action == "provision"
            else None
        )

        ext = f"vm-{name}-{action}-{uuid.uuid4().hex}"
        self._runs[ext] = {
            **backend,
            "name": name,
            "image": backend["image"],
            "os": vm_os,
            "action": action,
            "template_vm_id": backend.get("template_vm_id", ""),
            "template_node_name": backend.get("template_node_name", ""),
            "node_name": backend.get("node_name", ""),
            "clone_datastore_id": backend.get("clone_datastore_id", ""),
            "template": backend["template"],
            "resources": resources,
            "lifetime": lifetime,
            "status": RunStatus.PENDING,
            "with": step.with_,
            "artifacts": [],
        }
        return RunHandle(
            spider=self.NAME,
            external_id=ext,
            metadata={"name": name, "action": raw_action, "image": backend["image"]},
        )

    @staticmethod
    async def _stop_process(proc) -> None:
        """Interrupt OpenTofu and its provider children, then reap the process."""
        if proc.returncode is not None:
            return
        try:
            os.killpg(proc.pid, signal.SIGINT)
        except ProcessLookupError:
            pass
        try:
            # This bounds cancellation cleanup, never provisioning runtime.
            await asyncio.wait_for(proc.communicate(), timeout=10)
        except asyncio.TimeoutError:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await proc.communicate()

    async def _run_cmd(
        self, cmd: list[str], *, cwd: Path, env: dict[str, str]
    ) -> AsyncIterator[LogLine]:
        yield LogLine(f"$ {' '.join(cmd)}", "system")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            assert proc.stdout is not None
            async for raw in proc.stdout:
                yield LogLine(raw.decode(errors="replace").rstrip("\n"))
            await proc.wait()
        finally:
            await self._stop_process(proc)
        if proc.returncode != 0:
            raise RuntimeError(f"OpenTofu exited with code {proc.returncode}")

    async def _output(
        self, key: str, *, cwd: Path, env: dict[str, str], state_path: Path
    ) -> str:
        proc = await asyncio.create_subprocess_exec(
            "tofu",
            "output",
            f"-state={state_path}",
            "-raw",
            key,
            cwd=str(cwd),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            out, _ = await proc.communicate()
        finally:
            await self._stop_process(proc)
        return out.decode(errors="replace").strip() if proc.returncode == 0 else ""

    async def stream_logs(self, handle: RunHandle) -> AsyncIterator[LogLine]:
        st = self._runs[handle.external_id]
        st["status"] = RunStatus.RUNNING
        name, vm_os, action = st["name"], st["os"], st["action"]
        source_dir = self._tofu_dir()

        if not shutil.which("tofu"):
            if self._dev_fallback_enabled():
                yield LogLine(
                    "tofu not found — synthesizing VM because TOFU_DEV_FALLBACK is enabled",
                    "system",
                )
                await asyncio.sleep(0.1)
                if action == "destroy":
                    self._finish_destroy(handle)
                    yield LogLine(f"VM destroyed (dev mode): {name}", "system")
                else:
                    self._finish(handle, ip="10.81.19.200", vm_id=f"dev-{name}")
                return
            st["status"] = RunStatus.FAILED
            yield LogLine(
                "Stand backend is unavailable: tofu binary not found", "stderr"
            )
            return

        if action == "provision" and not source_dir.is_dir():
            st["status"] = RunStatus.FAILED
            yield LogLine("Stand backend configuration is unavailable", "stderr")
            return

        lock = None
        state_path = None
        operation_started = False
        try:
            state_dir = self._state_dir(name, st.get("connection", ""))
            state_dir.mkdir(parents=True, exist_ok=True)
            lock = (state_dir / ".arachne.lock").open("a")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError(
                    "Another operation owns this stand; retry after it completes"
                )
            if action == "destroy":
                work_dir, state_path = (
                    state_dir / "module",
                    state_dir / "terraform.tfstate",
                )
            else:
                state_path = state_dir / "terraform.tfstate"
                if state_path.exists():
                    raise ValueError(
                        "Stand state already exists; destroy it before provisioning again"
                    )
                work_dir, state_path = self._prepare_workdir(
                    name, source_dir, st.get("connection", "")
                )
            env = self._tofu_env(work_dir)
            from infrastructure_connections import execution_env

            if self.NAME != "tofu-proxmox":
                for key in list(env):
                    if key.startswith("PROXMOX_VE_"):
                        env.pop(key)
            env.update(
                execution_env(st.get("connection", ""), self.NAME.removeprefix("tofu-"))
            )
            if action == "destroy" and not state_path.exists():
                raise ValueError(f"No managed stand state found for {name}")
            # Save exact non-secret creation inputs for deletion after profile changes.
            manifest = state_dir / "arachne-inputs.json"
            if action == "destroy" and manifest.exists():
                vars_ = json.loads(manifest.read_text())["vars"]
            else:
                vars_ = self._vars(st)
                if action == "provision":
                    if state_path.exists():
                        raise ValueError(
                            "Stand state already exists; destroy it before provisioning again"
                        )
                    temp = manifest.with_suffix(".tmp")
                    temp.write_text(json.dumps({"vars": vars_}))
                    temp.replace(manifest)

            if action == "destroy" and not state_path.exists():
                st["status"] = RunStatus.FAILED
                yield LogLine(f"No managed stand state found for {name}", "stderr")
                return

            async for line in self._run_cmd(
                ["tofu", "init", "-input=false"], cwd=work_dir, env=env
            ):
                yield line

            if action == "destroy":
                cmd = [
                    "tofu",
                    "destroy",
                    "-auto-approve",
                    "-input=false",
                    f"-state={state_path}",
                    *vars_,
                ]
                async for line in self._run_cmd(cmd, cwd=work_dir, env=env):
                    yield line
                state_path.unlink(missing_ok=True)
                self._finish_destroy(handle)
                yield LogLine(f"Stand destroyed: {name}", "system")
                return

            operation_started = True
            cmd = [
                "tofu",
                "apply",
                "-auto-approve",
                "-input=false",
                f"-state={state_path}",
                *vars_,
            ]
            async for line in self._run_cmd(cmd, cwd=work_dir, env=env):
                yield line

            ip = await self._output(
                "vm_ip", cwd=work_dir, env=env, state_path=state_path
            )
            vm_id = await self._output(
                "vm_id", cwd=work_dir, env=env, state_path=state_path
            )

            if not vm_id:
                raise RuntimeError(
                    "OpenTofu returned no vm_id output; inspect the saved state"
                )

            # Retain machine identity before waiting for a guest agent.
            self._finish(handle, ip=ip, vm_id=vm_id)
            st["status"] = RunStatus.RUNNING
            yield LogLine("Waiting for guest IP address", "system")
            ip = await self._resolve_ip(st, vm_id, ip)
            self._finish(handle, ip=ip, vm_id=vm_id)
            if not ip:
                st["status"] = RunStatus.FAILED
                yield LogLine(
                    "Stand was created, but its IP address is not available yet",
                    "stderr",
                )
                return

            yield LogLine(f"Stand ready: {name} @ {ip} ({vm_os})", "system")
        except (OSError, RuntimeError, ValueError) as exc:
            st["status"] = RunStatus.FAILED
            handle.metadata["error"] = str(exc)
            yield LogLine(str(exc), "stderr")
        finally:
            # On a failed/cancelled apply retain any partially created VM identity.
            # Cleanup can then use the saved state even if the guest never booted.
            if (
                operation_started
                and not st["artifacts"]
                and state_path
                and state_path.exists()
            ):
                try:
                    state = json.loads(state_path.read_text())
                    vm_type = (
                        "ovirt_vm"
                        if self.NAME == "tofu-ovirt"
                        else "proxmox_virtual_environment_vm"
                    )
                    vm = next(
                        a["attributes"]
                        for r in state.get("resources", [])
                        if r.get("type") == vm_type
                        for a in r.get("instances", [])
                        if a.get("attributes")
                    )
                    vm_id = str(vm.get("vm_id") or vm.get("id") or "")
                    if vm_id:
                        status = st["status"]
                        self._finish(handle, ip="", vm_id=vm_id)
                        st["status"] = status
                except (ValueError, OSError, KeyError, StopIteration):
                    pass
            if lock is not None:
                lock.close()

    async def _resolve_ip(self, st, vm_id, initial):
        return initial

    def _finish_destroy(self, handle: RunHandle) -> None:
        st = self._runs[handle.external_id]
        st["artifacts"] = [
            Artifact(
                name=st["name"],
                type="vm",
                location=st["name"],
                metadata={
                    "image": st["image"],
                    "os": st["os"],
                    "connection": st.get("connection", ""),
                    "backend": self.NAME,
                    "state": "destroyed",
                },
            )
        ]
        st["status"] = RunStatus.SUCCESS

    def _finish(self, handle: RunHandle, ip: str, vm_id: str = "") -> None:
        st = self._runs[handle.external_id]
        vm_os = st["os"]
        conn, port = CONN_BY_OS.get(vm_os, ("ssh", 22))
        requested = {
            key: value
            for key, value in {
                "cpu": st["resources"]["cpu"],
                "memory_gb": st["resources"]["memory_gb"],
                "disk_gb": st["resources"]["disk_gb"],
            }.items()
            if value is not None
        }
        st["artifacts"] = [
            Artifact(
                name=st["name"],
                type="vm",
                location=vm_id or st["name"],
                metadata={
                    "connection": st.get("connection", ""),
                    "credentials_ref": st.get("credentials_ref", ""),
                    "image": st["image"],
                    "os": vm_os,
                    "arch": "x86_64",
                    "ip": ip,
                    "conn": conn,
                    "port": port,
                    "ssh_port": port,
                    "vm_id": vm_id,
                    "template_vm_id": st["template_vm_id"],
                    "node_name": st["node_name"],
                    "template_node_name": st["template_node_name"],
                    "clone_datastore_id": st["clone_datastore_id"],
                    "golden": {
                        "cpu": st["template"].get("cpu"),
                        "memory_gb": st["template"].get("memory_gb"),
                        "disk_gb": st["template"].get("disk_gb"),
                        "disk_interface": st["template"].get("disk_interface"),
                        "disk_datastore": st["template"].get("disk_datastore"),
                    },
                    "requested_resources": requested,
                    "lifetime": st["lifetime"],
                    "backend": self.NAME,
                    "state": "running",
                },
            )
        ]
        st["status"] = RunStatus.SUCCESS

    def get_status(self, handle: RunHandle) -> RunStatus:
        return self._runs[handle.external_id]["status"]

    def get_artifacts(self, handle: RunHandle) -> list[Artifact]:
        return self._runs[handle.external_id]["artifacts"]
