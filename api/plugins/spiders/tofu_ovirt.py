"""Optional oVirt Brood backend."""

from __future__ import annotations
import asyncio
import ipaddress
from core.tofu import TofuSpider
from core.registry import register_spider
from golden_images import get_profile
from infrastructure_connections import get_connection
from ovirt_api import inspect_template, primary_ipv4


class TofuOvirtSpider(TofuSpider):
    NAME = "tofu-ovirt"
    MODULE = "ovirt"

    def _resolve_backend(self, values, *, action, name):
        connection = str(values.get("connection") or "").strip()
        if action == "destroy":
            if not connection:
                raise ValueError("Destroy requires the original connection key")
            get_connection(connection, "ovirt", require_enabled=False)
            return {
                "connection": connection,
                "image": "",
                "os": str(values.get("os") or "redos8"),
                "template": {},
            }
        image = str(values.get("image") or values.get("os") or "redos8")
        profile = get_profile(image)
        if not profile or profile.get("backend") != "ovirt":
            raise ValueError("Select an enabled oVirt golden image")
        if connection and connection != profile.get("connection"):
            raise ValueError("Golden image belongs to another connection")
        connection = profile.get("connection") or ""
        get_connection(connection, "ovirt")
        template = inspect_template(profile["template_id"], connection)
        cidr = str(values.get("ip_cidr") or "")
        if cidr and ipaddress.ip_network(cidr).version != 4:
            raise ValueError("ip_cidr must be an IPv4 network")
        return {
            "connection": connection,
            "image": image,
            "os": profile["os"],
            "template": template,
            "template_vm_id": profile["template_id"],
            "cluster_id": template["cluster_id"],
            "credentials_ref": profile.get("credentials_ref", ""),
            "ip_interface": str(values.get("ip_interface") or ""),
            "ip_cidr": cidr,
        }

    @classmethod
    def _resources(cls, values, template):
        raw = values.get("resources") or {}
        if not isinstance(raw, dict) or set(raw) - {"cpu", "memory_gb"}:
            raise ValueError(
                "oVirt resources supports cpu and memory_gb; disk layout is inherited from the golden image"
            )
        cpu = cls._positive_int(raw.get("cpu"), field="cpu")
        memory = cls._positive_int(raw.get("memory_gb"), field="memory_gb")
        return {"cpu": cpu, "memory_gb": memory, "disk_gb": None}

    @staticmethod
    def _vars(st):
        return [
            f"-var=stand_name={st['name']}",
            f"-var=template_id={st['template_vm_id']}",
            f"-var=cluster_id={st['cluster_id']}",
            f"-var=cpu={st['resources']['cpu'] or st['template']['cpu']}",
            f"-var=memory={st['resources']['memory_gb'] * 1024**3 if st['resources']['memory_gb'] else st['template']['memory_bytes']}",
        ]

    async def _resolve_ip(self, st, vm_id, initial):
        while True:
            ip = await asyncio.to_thread(
                primary_ipv4,
                vm_id,
                st["connection"],
                interface=st.get("ip_interface", ""),
                cidr=st.get("ip_cidr", ""),
            )
            if ip:
                return ip
            await asyncio.sleep(3)


register_spider(TofuOvirtSpider())
