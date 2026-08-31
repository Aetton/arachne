"""ProvisionSpider: manage ephemeral Proxmox VMs through OpenTofu.

Normal scenario contract is intentionally small: a stand name, a logical OS and,
optionally, user-facing resource wishes and lifetime. The spider maps those wishes
to backend-specific OpenTofu variables; scenarios never need to know Proxmox VM
IDs, nodes, storages, disk interfaces or provider details.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
from pathlib import Path
from typing import AsyncIterator

from core.lifetime import normalize_lifetime
from core.registry import register_spider
from core.spider import ProvisionSpider
from core.types import Artifact, LogLine, RunHandle, RunStatus, StepSpec

TOFU_ROOT = os.getenv("TOFU_ROOT", "../tofu")
TOFU_STATE_ROOT = os.getenv("TOFU_STATE_ROOT", "/tmp/arachne-tofu-state")

CONN_BY_OS = {
    "redos7": ("ssh", 22),
    "redos8": ("ssh", 22),
    "windows": ("winrm", 5985),
}

_TEMPLATE_ENV = {
    "redos7": "TOFU_TEMPLATE_REDOS7",
    "redos8": "TOFU_TEMPLATE_REDOS8",
    "windows": "TOFU_TEMPLATE_WINDOWS",
}

_TEMPLATE_NODE_ENV = {
    "redos7": "TOFU_TEMPLATE_REDOS7_NODE",
    "redos8": "TOFU_TEMPLATE_REDOS8_NODE",
    "windows": "TOFU_TEMPLATE_WINDOWS_NODE",
}

_TEMPLATE_DISK_INTERFACE_ENV = {
    "redos7": "TOFU_TEMPLATE_REDOS7_DISK_INTERFACE",
    "redos8": "TOFU_TEMPLATE_REDOS8_DISK_INTERFACE",
    "windows": "TOFU_TEMPLATE_WINDOWS_DISK_INTERFACE",
}

_TEMPLATE_DISK_DATASTORE_ENV = {
    "redos7": "TOFU_TEMPLATE_REDOS7_DISK_DATASTORE",
    "redos8": "TOFU_TEMPLATE_REDOS8_DISK_DATASTORE",
    "windows": "TOFU_TEMPLATE_WINDOWS_DISK_DATASTORE",
}

_TEMPLATE_DISK_SIZE_ENV = {
    "redos7": "TOFU_TEMPLATE_REDOS7_DISK_GB",
    "redos8": "TOFU_TEMPLATE_REDOS8_DISK_GB",
    "windows": "TOFU_TEMPLATE_WINDOWS_DISK_GB",
}

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")
_TRUE = {"1", "true", "yes", "on"}
_RESOURCE_KEYS = {"cpu", "memory_gb", "disk_gb"}


class TofuProxmoxSpider(ProvisionSpider):
    NAME = "tofu-proxmox"

    def __init__(self):
        self._runs: dict[str, dict] = {}

    def _tofu_dir(self) -> Path:
        for candidate in [
            Path(TOFU_ROOT) / "stand",
            Path(__file__).resolve().parents[3] / "tofu" / "stand",
        ]:
            if candidate.is_dir():
                return candidate.resolve()
        return (Path(TOFU_ROOT) / "stand").resolve()

    @staticmethod
    def _dev_fallback_enabled() -> bool:
        return os.getenv("TOFU_DEV_FALLBACK", "false").strip().lower() in _TRUE

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

    @classmethod
    def _resources(cls, values: dict, vm_os: str) -> dict[str, int | str | None]:
        raw = values.get("resources")
        if raw in (None, ""):
            raw = {}
        if not isinstance(raw, dict):
            raise ValueError("resources must be a mapping")

        unknown = sorted(set(raw) - _RESOURCE_KEYS)
        if unknown:
            raise ValueError(
                "Unknown resource options: " + ", ".join(unknown) + ". "
                "Supported: cpu, memory_gb, disk_gb"
            )

        cpu = cls._positive_int(raw.get("cpu"), field="cpu")
        memory_gb = cls._positive_int(raw.get("memory_gb"), field="memory_gb")
        disk_gb = cls._positive_int(raw.get("disk_gb"), field="disk_gb")

        disk_interface = ""
        disk_datastore = ""
        if disk_gb is not None:
            base_disk_raw = (
                os.getenv(_TEMPLATE_DISK_SIZE_ENV[vm_os])
                or os.getenv("TOFU_DEFAULT_GOLDEN_DISK_GB")
                or "40"
            )
            try:
                base_disk_gb = int(base_disk_raw)
            except ValueError as exc:
                raise ValueError(
                    f"Backend configuration {_TEMPLATE_DISK_SIZE_ENV[vm_os]} "
                    "must be an integer"
                ) from exc
            if disk_gb < base_disk_gb:
                raise ValueError(
                    f"resources.disk_gb={disk_gb} cannot be smaller than the "
                    f"{vm_os} stand baseline ({base_disk_gb} GiB)"
                )

            disk_interface = (
                os.getenv(_TEMPLATE_DISK_INTERFACE_ENV[vm_os])
                or os.getenv("TOFU_SYSTEM_DISK_INTERFACE")
                or "scsi0"
            ).strip()
            disk_datastore = (
                os.getenv(_TEMPLATE_DISK_DATASTORE_ENV[vm_os])
                or os.getenv("TOFU_CLONE_DATASTORE")
                or ""
            ).strip()
            if not disk_datastore:
                raise ValueError(
                    "Disk growth was requested, but the backend does not know the "
                    f"system disk datastore for {vm_os}. Configure "
                    f"{_TEMPLATE_DISK_DATASTORE_ENV[vm_os]}."
                )

        return {
            "cpu": cpu,
            "memory_gb": memory_gb,
            "memory_mb": memory_gb * 1024 if memory_gb is not None else None,
            "disk_gb": disk_gb,
            "disk_interface": disk_interface,
            "disk_datastore": disk_datastore,
        }

    @staticmethod
    def _template_vm_id(vm_os: str, values: dict) -> int | None:
        raw = values.get("template_vm_id")
        if raw in (None, ""):
            env_name = _TEMPLATE_ENV.get(vm_os)
            raw = os.getenv(env_name, "") if env_name else ""
        if raw in (None, ""):
            return None
        return int(raw)

    @staticmethod
    def _template_node_name(vm_os: str, values: dict) -> str:
        raw = values.get("template_node_name")
        if raw in (None, ""):
            env_name = _TEMPLATE_NODE_ENV.get(vm_os)
            raw = os.getenv(env_name, "") if env_name else ""
        return str(raw or "").strip()

    @staticmethod
    def _target_node_name(values: dict, template_node_name: str) -> str:
        raw = values.get("node_name") or os.getenv("TOFU_NODE_NAME")
        return str(raw or template_node_name or "").strip()

    @staticmethod
    def _clone_datastore_id(values: dict) -> str:
        raw = values.get("clone_datastore_id") or os.getenv("TOFU_CLONE_DATASTORE")
        return str(raw or "").strip()

    def _state_dir(self, name: str) -> Path:
        return Path(TOFU_STATE_ROOT).expanduser().resolve() / name

    def _prepare_workdir(self, name: str, source_dir: Path) -> tuple[Path, Path]:
        """Create an isolated module directory and state path for one stand."""
        state_dir = self._state_dir(name)
        work_dir = state_dir / "module"
        work_dir.mkdir(parents=True, exist_ok=True)

        copied = False
        for pattern in ("*.tf", "*.tf.json"):
            for src in source_dir.glob(pattern):
                shutil.copy2(src, work_dir / src.name)
                copied = True

        source_lock = source_dir / ".terraform.lock.hcl"
        if source_lock.exists():
            shutil.copy2(source_lock, work_dir / source_lock.name)

        if not copied:
            raise ValueError(f"No OpenTofu configuration files found in {source_dir}")

        return work_dir, state_dir / "terraform.tfstate"

    @staticmethod
    def _tofu_env(work_dir: Path) -> dict[str, str]:
        env = os.environ.copy()
        env["TF_DATA_DIR"] = str(work_dir / ".terraform")
        return env

    @staticmethod
    def _vars(st: dict) -> list[str]:
        args = [
            f"-var=stand_name={st['name']}",
            f"-var=os={st['os']}",
            f"-var=template_vm_id={st['template_vm_id']}",
            f"-var=node_name={st['node_name']}",
            f"-var=template_node_name={st['template_node_name']}",
            f"-var=clone_datastore_id={st['clone_datastore_id']}",
        ]
        resources = st["resources"]
        if resources["cpu"] is not None:
            args.append(f"-var=override_cpu={resources['cpu']}")
        if resources["memory_mb"] is not None:
            args.append(f"-var=override_memory_mb={resources['memory_mb']}")
        if resources["disk_gb"] is not None:
            args.extend([
                f"-var=override_disk_gb={resources['disk_gb']}",
                f"-var=override_disk_interface={resources['disk_interface']}",
                f"-var=override_disk_datastore_id={resources['disk_datastore']}",
            ])
        return args

    def dispatch(self, step: StepSpec, ctx) -> RunHandle:
        name = str(step.with_.get("name", "test-stand"))
        vm_os = str(step.with_.get("os", "redos8"))
        action = (step.action or "provision").strip().lower()

        self._validate_name(name)
        if vm_os not in CONN_BY_OS:
            raise ValueError(
                f"Unsupported stand OS {vm_os!r}; expected one of "
                f"{', '.join(sorted(CONN_BY_OS))}"
            )
        if action not in {"provision", "destroy"}:
            raise ValueError(
                f"Unsupported tofu-proxmox action {action!r}; use provision or destroy"
            )

        resources = self._resources(step.with_, vm_os)
        lifetime = normalize_lifetime(step.with_.get("lifetime")) if action == "provision" else None
        template_vm_id = self._template_vm_id(vm_os, step.with_)
        template_node_name = self._template_node_name(vm_os, step.with_)
        node_name = self._target_node_name(step.with_, template_node_name)
        clone_datastore_id = self._clone_datastore_id(step.with_)

        if template_vm_id is None and not self._dev_fallback_enabled():
            raise ValueError(
                f"Stand profile {vm_os!r} is not configured on the Arachne backend"
            )
        if not node_name and not self._dev_fallback_enabled():
            raise ValueError(
                f"Stand profile {vm_os!r} has no target host configured on the backend"
            )

        ext = f"vm-{name}-{action}"
        self._runs[ext] = {
            "name": name,
            "os": vm_os,
            "action": action,
            "template_vm_id": template_vm_id,
            "template_node_name": template_node_name,
            "node_name": node_name,
            "clone_datastore_id": clone_datastore_id,
            "resources": resources,
            "lifetime": lifetime,
            "status": RunStatus.PENDING,
            "with": step.with_,
            "artifacts": [],
        }
        return RunHandle(
            spider=self.NAME,
            external_id=ext,
            metadata={"name": name, "action": action},
        )

    async def _run_cmd(
        self,
        cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
    ) -> AsyncIterator[LogLine]:
        yield LogLine(f"$ {' '.join(cmd)}", "system")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert proc.stdout is not None
        async for raw in proc.stdout:
            yield LogLine(raw.decode(errors="replace").rstrip("\n"))
        await proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"OpenTofu exited with code {proc.returncode}")

    async def _output(
        self,
        key: str,
        *,
        cwd: Path,
        env: dict[str, str],
        state_path: Path,
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
        )
        out, _ = await proc.communicate()
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
            yield LogLine("Stand backend is unavailable: tofu binary not found", "stderr")
            return

        if not source_dir.is_dir():
            st["status"] = RunStatus.FAILED
            yield LogLine("Stand backend configuration is unavailable", "stderr")
            return

        try:
            work_dir, state_path = self._prepare_workdir(name, source_dir)
            env = self._tofu_env(work_dir)
            vars_ = self._vars(st)

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
                self._finish_destroy(handle)
                yield LogLine(f"Stand destroyed: {name}", "system")
                return

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

            # Once the backend has a VM ID, lifecycle ownership must be preserved
            # even if guest-agent/IP discovery fails. Failed steps still return
            # their artifacts through the thread adapter.
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
            yield LogLine(str(exc), "stderr")

    def _finish_destroy(self, handle: RunHandle) -> None:
        st = self._runs[handle.external_id]
        st["artifacts"] = [
            Artifact(
                name=st["name"],
                type="vm",
                location=st["name"],
                metadata={
                    "os": st["os"],
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


register_spider(TofuProxmoxSpider())
