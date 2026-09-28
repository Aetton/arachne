"""oVirt REST discovery for the optional tofu-ovirt backend; no SDK required."""

from __future__ import annotations
import ipaddress
import ssl
from uuid import UUID
import httpx
from infrastructure_connections import execution_env


def _client(connection):
    env = execution_env(connection, "ovirt")
    verify = (
        False
        if env["TF_VAR_ovirt_insecure"] == "true"
        else ssl.create_default_context(cafile=env["TF_VAR_ovirt_ca_file"] or None)
    )
    return httpx.Client(
        base_url=env["TF_VAR_ovirt_url"].rstrip("/") + "/",
        auth=(env["TF_VAR_ovirt_username"], env["TF_VAR_ovirt_password"]),
        headers={"Accept": "application/json"},
        verify=verify,
        timeout=15,
    )


def _get(client, path):
    try:
        response = client.get(path)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        # Do not propagate response bodies, which can contain sensitive data.
        raise ValueError(
            f"oVirt API request failed for {path}: {type(exc).__name__}"
        ) from exc
    if not isinstance(data, dict):
        raise ValueError("Unexpected oVirt API response")
    return data


def _details(t):
    topology = (t.get("cpu") or {}).get("topology") or {}
    cpu = 1
    for k in ("cores", "sockets", "threads"):
        cpu *= int(topology.get(k) or 1)
    return {
        "vm_id": str(t["id"]),
        "name": t.get("name", t["id"]),
        "cluster_id": (t.get("cluster") or {}).get("id", ""),
        "node": (t.get("cluster") or {}).get("id", ""),
        "cpu": cpu,
        "memory_gb": round(int(t.get("memory") or 0) / 1024**3, 2),
        "memory_bytes": int(t.get("memory") or 0),
        "disk_gb": None,
    }


def list_templates(connection):
    with _client(connection) as client:
        return [
            _details(t)
            for t in _get(client, "templates").get("template", [])
            if t.get("id") != "00000000-0000-0000-0000-000000000000"
            and t.get("status") == "ok"
        ]


def inspect_template(template_id, connection):
    template_id = str(UUID(str(template_id)))
    with _client(connection) as client:
        t = _get(client, f"templates/{template_id}")
    if t.get("status") != "ok":
        raise ValueError("oVirt template is not ready")
    result = _details(t)
    if not result["cluster_id"]:
        raise ValueError("Template has no cluster; use a cluster-bound golden template")
    return result


def primary_ipv4(vm_id, connection, *, interface="", cidr=""):
    vm_id = str(UUID(str(vm_id)))
    network = ipaddress.ip_network(cidr) if cidr else None
    with _client(connection) as client:
        devices = _get(client, f"vms/{vm_id}/reporteddevices").get(
            "reported_device", []
        )
    candidates = set()
    for dev in devices:
        if interface and dev.get("name") != interface:
            continue
        for entry in (dev.get("ips") or {}).get("ip", []):
            try:
                ip = ipaddress.ip_address(entry.get("address", ""))
            except ValueError:
                continue
            if (
                ip.version != 4
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_unspecified
            ):
                continue
            if network and ip not in network:
                continue
            candidates.add(str(ip))
    if len(candidates) > 1:
        raise ValueError(
            "Several guest IPv4 addresses match; set ip_interface and/or ip_cidr"
        )
    return next(iter(candidates), "")
