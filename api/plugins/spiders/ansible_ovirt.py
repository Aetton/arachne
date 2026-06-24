"""ProvisionSpider stub: oVirt via Ansible (ovirt.ovirt collection).

This is the template for "tofu is weak at oVirt, ansible has the full kit".
Same contract as tofu-proxmox — swapping `driver: tofu-proxmox` to
`driver: ansible-ovirt` in a scenario is the only change needed.

Fill in the playbook call; the artifact shape is already correct.
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from core.spider import ProvisionSpider
from core.registry import register_spider
from core.types import RunHandle, LogLine, RunStatus, Artifact, StepSpec

CONN_BY_OS = {"redos7": ("ssh", 22), "redos8": ("ssh", 22), "windows": ("winrm", 5985)}


class AnsibleOvirtSpider(ProvisionSpider):
    NAME = "ansible-ovirt"

    def __init__(self):
        self._runs: dict[str, dict] = {}

    def dispatch(self, step: StepSpec, ctx) -> RunHandle:
        name = step.with_.get("name", "test-stand")
        ext = f"ovirt-{name}"
        self._runs[ext] = {"name": name, "os": step.with_.get("os", "redos8"),
                           "with": step.with_, "status": RunStatus.PENDING, "artifacts": []}
        return RunHandle(spider=self.NAME, external_id=ext, metadata={"name": name})

    async def stream_logs(self, handle: RunHandle) -> AsyncIterator[LogLine]:
        st = self._runs[handle.external_id]
        st["status"] = RunStatus.RUNNING
        # TODO: ansible-playbook provision-ovirt.yml -e name=.. -e os=..
        #       using the ovirt.ovirt collection (vms_module).
        yield LogLine("ansible-ovirt: stub — wire up ovirt.ovirt playbook here", "system")
        await asyncio.sleep(0.2)

        vm_os = st["os"]
        conn, port = CONN_BY_OS.get(vm_os, ("ssh", 22))
        st["artifacts"] = [Artifact(
            name=st["name"], type="vm", location=st["name"],
            metadata={"os": vm_os, "ip": "10.81.19.210", "conn": conn,
                      "ssh_port": port, "backend": self.NAME, "state": "running"},
        )]
        st["status"] = RunStatus.SUCCESS

    def get_status(self, handle: RunHandle) -> RunStatus:
        return self._runs[handle.external_id]["status"]

    def get_artifacts(self, handle: RunHandle) -> list[Artifact]:
        return self._runs[handle.external_id]["artifacts"]


register_spider(AnsibleOvirtSpider())
