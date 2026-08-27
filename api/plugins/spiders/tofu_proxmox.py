"""ProvisionSpider: manage ephemeral Proxmox VMs through OpenTofu.

The scenario talks in infrastructure terms (OS/resources), while the spider maps
those values to concrete Proxmox templates and keeps one isolated local state per
stand.  The OpenTofu module remains backend-specific; scenarios do not need to
know VM IDs, datastore names or bridges.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
from pathlib import Path
from typing import AsyncIterator

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

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")
_TRUE = {"1", "true", "yes", "on"}


class TofuProxmoxSpider(ProvisionSpider):
    NAME = "tofu-proxmox"

    def __init__(self):
        self._runs: dict[str, dict] = {}

    def _tofu_dir(self) -> str:
        for candidate in [
            os.path.join(TOFU_ROOT, "stand"),
            os.path.join(
                os.path.dirname(__file__), "..", "..", "..", "tofu", "stand"
            ),
        ]:
            if os.path.isdir(candidate):
                return os.path.abspath(candidate)
        return os.path.abspath(os.path.join(TOFU_ROOT, "stand"))

    @staticmethod
    def _dev_fallback_enabled() -> bool:
        return os.getenv("TOFU_DEV_FALLBACK", "false").strip().lower() in _TRUE

    @staticmethod
    def _validate_name(name: str) -> None:
        if not _NAME_RE.fullmatch(name):
            raise ValueError(
                "OpenTofu stand name must start with an alphanumeric character "
                "and contain only letters, digits, '.', '_' or '-' (max 63 chars)"
            )

    @staticmethod
    def _template_vm_id(vm_os: str, values: dict) -> int | None:
        # Explicit override is useful for diagnostics, but normal scenarios should
        # rely on the per-OS environment mapping.
        raw = values.get("template_vm_id")
        if raw in (None, ""):
            env_name = _TEMPLATE_ENV.get(vm_os)
            raw = os.getenv(env_name, "") if env_name else ""
        if raw in (None, ""):
            return None
        return int(raw)

    def _state_dir(self, name: str) -> Path:
        return Path(TOFU_STATE_ROOT).expanduser().resolve() / name

    def _tofu_env(self, name: str) -> tuple[dict[str, str], Path]:
        state_dir = self._state_dir(name)
        state_dir.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["TF_DATA_DIR"] = str(state_dir / ".terraform")
        return env, state_dir / "terraform.tfstate"

    @staticmethod
    def _vars(st: dict) -> list[str]:
        values = st["with"]
        template_vm_id = st["template_vm_id"]
        return [
            f"-var=stand_name={st['name']}",
            f"-var=os={st['os']}",
            f"-var=template_vm_id={template_vm_id}",
            f"-var=vcpus={int(values.get('vcpus', 4))}",
            f"-var=ram_mb={int(values.get('ram_mb', 8192))}",
            f"-var=disk_gb={int(values.get('disk_gb', 40))}",
            f"-var=node_name={values.get('node_name', os.getenv('TOFU_NODE_NAME', 'pve'))}",
            f"-var=datastore_id={values.get('datastore_id', os.getenv('TOFU_DATASTORE', 'local-lvm'))}",
            f"-var=bridge={values.get('bridge', os.getenv('TOFU_BRIDGE', 'vmbr0'))}",
            f"-var=disk_interface={values.get('disk_interface', os.getenv('TOFU_DISK_INTERFACE', 'scsi0'))}",
        ]

    def dispatch(self, step: StepSpec, ctx) -> RunHandle:
        name = str(step.with_.get("name", "test-stand"))
        vm_os = str(step.with_.get("os", "redos8"))
        action = (step.action or "provision").strip().lower()

        self._validate_name(name)
        if vm_os not in CONN_BY_OS:
            raise ValueError(
                f"Unsupported OpenTofu OS {vm_os!r}; expected one of "
                f"{', '.join(sorted(CONN_BY_OS))}"
            )
        if action not in {"provision", "destroy"}:
            raise ValueError(
                f"Unsupported tofu-proxmox action {action!r}; use provision or destroy"
            )

        template_vm_id = self._template_vm_id(vm_os, step.with_)
        if template_vm_id is None and not self._dev_fallback_enabled():
            env_name = _TEMPLATE_ENV[vm_os]
            raise ValueError(
                f"No Proxmox template configured for {vm_os}: set {env_name} "
                "or with.template_vm_id"
            )

        ext = f"vm-{name}-{action}"
        self._runs[ext] = {
            "name": name,
            "os": vm_os,
            "action": action,
            "template_vm_id": template_vm_id,
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
        cwd: str,
        env: dict[str, str],
    ) -> AsyncIterator[LogLine]:
        yield LogLine(f"$ {' '.join(cmd)}", "system")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
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
        cwd: str,
        env: dict[str, str],
        state_path: Path,
    ) -> str:
        proc = await asyncio.create_subprocess_exec(
            "tofu",
            "output",
            f"-state={state_path}",
            "-raw",
            key,
            cwd=cwd,
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
        tofu_dir = self._tofu_dir()

        if not shutil.which("tofu"):
            if self._dev_fallback_enabled():
                yield LogLine(
                    "tofu not found — synthesizing VM because TOFU_DEV_FALLBACK is enabled",
                    "system",
                )
                await asyncio.sleep(0.1)
                if action == "destroy":
                    st["status"] = RunStatus.SUCCESS
                    yield LogLine(f"VM destroyed (dev mode): {name}", "system")
                else:
                    self._finish(handle, ip="10.81.19.200", vm_id="dev")
                return
            st["status"] = RunStatus.FAILED
            yield LogLine("tofu binary not found", "stderr")
            return

        if not os.path.isdir(tofu_dir):
            st["status"] = RunStatus.FAILED
            yield LogLine(f"OpenTofu module not found: {tofu_dir}", "stderr")
            return

        env, state_path = self._tofu_env(name)
        vars_ = self._vars(st)

        try:
            async for line in self._run_cmd(
                ["tofu", "init", "-input=false"], cwd=tofu_dir, env=env
            ):
                yield line

            if action == "destroy":
                if not state_path.exists():
                    st["status"] = RunStatus.FAILED
                    yield LogLine(
                        f"No OpenTofu state for stand {name}: {state_path}", "stderr"
                    )
                    return
                cmd = [
                    "tofu",
                    "destroy",
                    "-auto-approve",
                    "-input=false",
                    f"-state={state_path}",
                    *vars_,
                ]
                async for line in self._run_cmd(cmd, cwd=tofu_dir, env=env):
                    yield line
                st["status"] = RunStatus.SUCCESS
                st["artifacts"] = []
                yield LogLine(f"VM destroyed: {name}", "system")
                return

            cmd = [
                "tofu",
                "apply",
                "-auto-approve",
                "-input=false",
                f"-state={state_path}",
                *vars_,
            ]
            async for line in self._run_cmd(cmd, cwd=tofu_dir, env=env):
                yield line

            ip = await self._output(
                "vm_ip", cwd=tofu_dir, env=env, state_path=state_path
            )
            vm_id = await self._output(
                "vm_id", cwd=tofu_dir, env=env, state_path=state_path
            )
            if not ip:
                st["status"] = RunStatus.FAILED
                yield LogLine(
                    "VM was created, but OpenTofu did not return vm_ip. "
                    "Check qemu-guest-agent in the template.",
                    "stderr",
                )
                return

            self._finish(handle, ip=ip, vm_id=vm_id)
            yield LogLine(f"VM ready: {name} @ {ip} ({vm_os})", "system")
        except (OSError, RuntimeError, ValueError) as exc:
            st["status"] = RunStatus.FAILED
            yield LogLine(str(exc), "stderr")

    def _finish(self, handle: RunHandle, ip: str, vm_id: str = "") -> None:
        st = self._runs[handle.external_id]
        vm_os = st["os"]
        conn, port = CONN_BY_OS.get(vm_os, ("ssh", 22))
        values = st["with"]
        st["artifacts"] = [
            Artifact(
                name=st["name"],
                type="vm",
                location=vm_id or st["name"],
                metadata={
                    "os": vm_os,
                    "arch": "x86_64",
                    "hostname": f"{st['name']}.redsoft.internal",
                    "ip": ip,
                    "conn": conn,
                    "ssh_port": port,
                    "vcpus": int(values.get("vcpus", 4)),
                    "ram_mb": int(values.get("ram_mb", 8192)),
                    "disk_gb": int(values.get("disk_gb", 40)),
                    "vm_id": vm_id,
                    "template_vm_id": st["template_vm_id"],
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
