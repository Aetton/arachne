"""Optional Proxmox Brood backend."""

from __future__ import annotations
from core.tofu import TofuSpider, CONN_BY_OS
from core.registry import register_spider
from database import ManagedMachine, SessionLocal
from golden_images import get_profile
from proxmox_api import ProxmoxAPIError, inspect_template

_RESOURCE_KEYS = {"cpu", "memory_gb", "disk_gb"}
_ACTIVE_MACHINE_STATES = {"running", "ready", "destroying", "reap_failed"}


class TofuProxmoxSpider(TofuSpider):
    NAME = "tofu-proxmox"
    MODULE = "stand"

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

    @classmethod
    def _managed_backend(cls, name: str, connection: str = "") -> dict | None:
        db = SessionLocal()
        try:
            row = (
                db.query(ManagedMachine)
                .filter(
                    ManagedMachine.backend == cls.NAME,
                    ManagedMachine.name == name,
                    ManagedMachine.state.in_(_ACTIVE_MACHINE_STATES),
                )
                .order_by(ManagedMachine.id.desc())
                .all()
            )
            row = next(
                (
                    r
                    for r in row
                    if (r.backend_metadata or {}).get("connection", "") == connection
                ),
                None,
            )
            if not row:
                return None
            md = dict(row.backend_metadata or {})
            if not md.get("template_vm_id") or not md.get("template_node_name"):
                return None
            return {
                "connection": connection,
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
        connection = str(values.get("connection") or "").strip()
        if action == "destroy":
            original = self._managed_backend(name, connection)
            if original:
                return original
            # Destroy needs only saved state, never a live template.
            return {
                "connection": connection,
                "image": "",
                "os": str(values.get("os") or "redos8"),
                "template": {},
            }

        profile_key = (
            str(values.get("image") or values.get("os") or "redos8").strip().lower()
        )
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

        if profile.get("backend", "proxmox") != "proxmox":
            raise ValueError("Golden image belongs to another backend")
        profile_connection = profile.get("connection") or ""
        if connection and connection != profile_connection:
            raise ValueError("Golden image belongs to another connection")
        connection = profile_connection
        from infrastructure_connections import get_connection

        if connection:
            get_connection(connection, "proxmox")
        vm_os = str(profile["os"])
        if vm_os not in CONN_BY_OS:
            raise ValueError(
                f"Golden image profile {profile_key!r} has unsupported OS {vm_os!r}"
            )

        try:
            template = inspect_template(int(profile["vm_id"]), connection=connection)
        except ProxmoxAPIError as exc:
            raise ValueError(
                f"Golden image profile {profile_key!r} is unavailable: {exc}"
            ) from exc

        node = str(template.get("node") or "")
        if not node:
            raise ValueError(
                f"Golden image profile {profile_key!r} has no Proxmox node"
            )

        return {
            "connection": connection,
            "credentials_ref": profile.get("credentials_ref", ""),
            "image": profile_key,
            "os": vm_os,
            "template_vm_id": int(template["vm_id"]),
            "template_node_name": node,
            "node_name": node,
            "clone_datastore_id": "",
            "template": template,
        }

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
            args.extend(
                [
                    f"-var=override_disk_gb={resources['disk_gb']}",
                    f"-var=override_disk_interface={resources['disk_interface']}",
                    f"-var=override_disk_datastore_id={resources['disk_datastore']}",
                ]
            )
        return args


register_spider(TofuProxmoxSpider())
