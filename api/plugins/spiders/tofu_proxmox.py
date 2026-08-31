"""ProvisionSpider: manage ephemeral Proxmox VMs through OpenTofu.

Scenario authors choose a human golden-image profile. The profile stores only the
selected Proxmox template VM ID; node, storage, disk layout and baseline resources
are discovered from Proxmox at dispatch time.
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
from database import ManagedMachine, SessionLocal
from golden_images import get_profile
from proxmox_api import ProxmoxAPIError, inspect_template

TOFU_ROOT = os.getenv("TOFU_ROOT", "../tofu")
TOFU_STATE_ROOT = os.getenv("TOFU_STATE_ROOT", "/tmp/arachne-tofu-state")

CONN_BY_OS = {
    "redos7": ("ssh", 22),
    "redos8": ("ssh", 22),
    "windows": ("winrm", 5985),
}

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")
_TRUE = {"1", "true", "yes", "on"}
_RESOURCE_KEYS = {"cpu", "memory_gb", "disk_gb"}
_ACTIVE_MACHINE_STATES = {"running", "ready", "destroying", "reap_failed"}


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
    def _resources(cls, values: dict, template: dict) -> dict[str, int | str | None]:
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
            base_disk_gb = template.get("disk_gb")
            if base_disk_gb is None:
                raise ValueError(
                    "The selected golden image has no discoverable system disk size"
                )
            if disk_gb < int(base_disk_gb):
                raise ValueError(
                    f"resources.disk_gb={disk_gb} cannot be smaller than the "
                    f"golden image system disk ({base_disk_gb} GiB)"
                )
            disk_interface = str(template.get("disk_interface") or "")
            disk_datastore = str(template.get("disk_datastore") or "")
            if not disk_interface or not disk_datastore:
                raise ValueError(
                    "The selected golden image system disk placement could not be discovered"
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
    def _managed_backend(name: str) -> dict | None:
        """Return the original backend facts for a managed VM before destroy.

        This keeps destroy stable if an admin changes the golden-image mapping
        after the stand has already been created.
        """
        db = SessionLocal()
        try:
            row = db.query(ManagedMachine).filter(
                ManagedMachine.backend == "tofu-proxmox",
                ManagedMachine.name == name,
                ManagedMachine.state.in_(_ACTIVE_MACHINE_STATES),
            ).order_by(ManagedMachine.id.desc()).first()
            if not row:
                return None
            md = dict(row.backend_metadata or {})
            if not md.get("template_vm_id") or not md.get("template_node_name"):
                return None
            return {
                "image": str(md.get("image") or md.get("os") or ""),
                "os": str(md.get("os") or "redos8"),
                "template_vm_id": int(md["template_vm_id"]),
                "template_node_name": str(md["template_node_name"]),
                "node_name": str(md.get("node_name") or md["template_node_name"]),
                "clone_datastore_id": str(md.get("clone_datastore_id") or ""),
                "template": {
                    "vm_id": int(md["template_vm_id"]),
                    "node": str(md["template_node_name"]),
                    "disk_gb": None,
                    "disk_interface": "",
                    "disk_datastore": "",
                },
            }
        finally:
            db.close()

    def _resolve_backend(self, values: dict, *, action: str, name: str) -> dict:
        if action == "destroy":
            original = self._managed_backend(name)
            if original:
                return original

        profile_key = str(values.get("image") or values.get("os") or "redos8").strip().lower()
        profile = get_profile(profile_key)
        if not profile:
            if self._dev_fallback_enabled():
                vm_os = str(values.get("os") or "redos8")
                return {
                    "image": profile_key,
                    "os": vm_os,
                    "template_vm_id": 0,
                    "template_node_name": "dev",
                    "node_name": "dev",
                    "clone_datastore_id": "",
                    "template": {
                        "vm_id": 0,
                        "node": "dev",
                        "disk_gb": 40,
                        "disk_interface": "scsi0",
                        "disk_datastore": "dev",
                    },
                }
            raise ValueError(
                f"Golden image profile {profile_key!r} is not configured. "
                "Ask an Arachne administrator to map it in Control → Golden Images."
            )

        vm_os = str(profile["os"])
        if vm_os not in CONN_BY_OS:
            raise ValueError(f"Golden image profile {profile_key!r} has unsupported OS {vm_os!r}")

        try:
            template = inspect_template(int(profile["vm_id"]))
        except ProxmoxAPIError as exc:
            raise ValueError(
                f"Golden image profile {profile_key!r} is unavailable: {exc}"
            ) from exc

        node = str(template.get("node") or "")
        if not node:
            raise ValueError(f"Golden image profile {profile_key!r} has no Proxmox node")

        return {
            "image": profile_key,
            "os": vm_os,
            "template_vm_id": int(template["vm_id"]),
            "template_node_name": node,
            "node_name": node,
            "clone_datastore_id": "",
            "template": template,
        }

    def _state_dir(self, name: str) -> Path:
        return Path(TOFU_STATE_ROOT).expanduser().resolve() / name

    def _prepare_workdir(self, name: str, source_dir: Path) -> tuple[Path, Path]:
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
        action = (step.action or "provision").strip().lower()
        self._validate_name(name)
        if action not in {"provision", "destroy"}:
            raise ValueError(
                f"Unsupported tofu-proxmox action {action!r}; use provision or destroy"
            )

        backend = self._resolve_backend(step.with_, action=action, name=name)
        vm_os = backend["os"]
        resources = self._resources(step.with_, backend["template"]) if action == "provision" else {
            "cpu": None,
            "memory_gb": None,
            "memory_mb": None,
            "disk_gb": None,
            "disk_interface": "",
            "disk_datastore": "",
        }
        lifetime = normalize_lifetime(step.with_.get("lifetime")) if action == "provision" else None

        ext = f"vm-{name}-{action}"
        self._runs[ext] = {
            "name": name,
            "image": backend["image"],
            "os": vm_os,
            "action": action,
            "template_vm_id": backend["template_vm_id"],
            "template_node_name": backend["template_node_name"],
            "node_name": backend["node_name"],
            "clone_datastore_id": backend["clone_datastore_id"],
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
            metadata={"name": name, "action": action, "image": backend["image"]},
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
            "tofu", "output", f"-state={state_path}", "-raw", key,
            cwd=str(cwd), env=env,
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
                    "tofu", "destroy", "-auto-approve", "-input=false",
                    f"-state={state_path}", *vars_,
                ]
                async for line in self._run_cmd(cmd, cwd=work_dir, env=env):
                    yield line
                self._finish_destroy(handle)
                yield LogLine(f"Stand destroyed: {name}", "system")
                return

            cmd = [
                "tofu", "apply", "-auto-approve", "-input=false",
                f"-state={state_path}", *vars_,
            ]
            async for line in self._run_cmd(cmd, cwd=work_dir, env=env):
                yield line

            ip = await self._output("vm_ip", cwd=work_dir, env=env, state_path=state_path)
            vm_id = await self._output("vm_id", cwd=work_dir, env=env, state_path=state_path)

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
                    "image": st["image"],
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


register_spider(TofuProxmoxSpider())
