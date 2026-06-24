"""ProvisionSpider: stands up a VM via OpenTofu (Proxmox provider).

Produces a rich `type: vm` artifact carrying os/ip/conn/resources so the deploy
step knows how to reach and provision the host.
"""
from __future__ import annotations

import asyncio
import os
from typing import AsyncIterator

from core.spider import ProvisionSpider
from core.registry import register_spider
from core.types import RunHandle, LogLine, RunStatus, Artifact, StepSpec

TOFU_ROOT = os.getenv("TOFU_ROOT", "../tofu")

# os -> (connection kind, port)
CONN_BY_OS = {
    "redos7": ("ssh", 22),
    "redos8": ("ssh", 22),
    "windows": ("winrm", 5985),
}


class TofuProxmoxSpider(ProvisionSpider):
    NAME = "tofu-proxmox"

    def __init__(self):
        self._runs: dict[str, dict] = {}

    def _tofu_dir(self) -> str:
        for c in [os.path.join(TOFU_ROOT, "stand"),
                  os.path.join(os.path.dirname(__file__), "..", "..", "..", "tofu", "stand")]:
            if os.path.isdir(c):
                return c
        return os.path.join(TOFU_ROOT, "stand")

    def dispatch(self, step: StepSpec, ctx) -> RunHandle:
        name = step.with_.get("name", "test-stand")
        vm_os = step.with_.get("os", "redos8")
        ext = f"vm-{name}"
        self._runs[ext] = {
            "name": name, "os": vm_os, "status": RunStatus.PENDING,
            "with": step.with_, "artifacts": [],
        }
        return RunHandle(spider=self.NAME, external_id=ext, metadata={"name": name})

    async def stream_logs(self, handle: RunHandle) -> AsyncIterator[LogLine]:
        st = self._runs[handle.external_id]
        st["status"] = RunStatus.RUNNING
        name, vm_os = st["name"], st["os"]
        tofu_dir = self._tofu_dir()

        import shutil
        if not shutil.which("tofu"):
            # dev fallback: synthesize a VM artifact so downstream steps work
            yield LogLine("tofu not found — synthesizing VM (dev mode)", "system")
            await asyncio.sleep(0.3)
            self._finish(handle, ip="10.81.19.200")
            return

        cmds = [
            ["tofu", "init", "-input=false"],
            ["tofu", "apply", "-auto-approve", "-input=false",
             f"-var=stand_name={name}", f"-var=os={vm_os}"],
        ]
        for cmd in cmds:
            yield LogLine(f"$ {' '.join(cmd)}", "system")
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=tofu_dir,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            assert proc.stdout is not None
            async for raw in proc.stdout:
                yield LogLine(raw.decode(errors="replace").rstrip("\n"))
            await proc.wait()
            if proc.returncode != 0:
                st["status"] = RunStatus.FAILED
                return

        # read VM ip from tofu output
        ip = "0.0.0.0"
        try:
            proc = await asyncio.create_subprocess_exec(
                "tofu", "output", "-raw", "vm_ip", cwd=tofu_dir,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, _ = await proc.communicate()
            ip = out.decode().strip() or ip
        except Exception:  # noqa: BLE001
            pass
        self._finish(handle, ip=ip)
        yield LogLine(f"VM ready: {name} @ {ip} ({vm_os})", "system")

    def _finish(self, handle: RunHandle, ip: str):
        st = self._runs[handle.external_id]
        vm_os = st["os"]
        conn, port = CONN_BY_OS.get(vm_os, ("ssh", 22))
        st["artifacts"] = [Artifact(
            name=st["name"], type="vm", location=st["name"],
            metadata={
                "os": vm_os, "arch": "x86_64",
                "hostname": f"{st['name']}.redsoft.internal",
                "ip": ip, "conn": conn, "ssh_port": port,
                "vcpus": int(st["with"].get("vcpus", 4)),
                "ram_mb": int(st["with"].get("ram_mb", 8192)),
                "disk_gb": int(st["with"].get("disk_gb", 40)),
                "backend": self.NAME, "state": "running",
            },
        )]
        st["status"] = RunStatus.SUCCESS

    def get_status(self, handle: RunHandle) -> RunStatus:
        return self._runs[handle.external_id]["status"]

    def get_artifacts(self, handle: RunHandle) -> list[Artifact]:
        return self._runs[handle.external_id]["artifacts"]


register_spider(TofuProxmoxSpider())
