"""Small Proxmox VE API client used by Arachne infrastructure plugins.

Only connection details live in environment variables. Template placement and
hardware are discovered from Proxmox itself so Arachne does not duplicate node,
storage, disk interface, CPU or RAM configuration.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx


class ProxmoxAPIError(RuntimeError):
    pass


def _settings() -> tuple[str, str, bool | str]:
    endpoint = os.getenv("PROXMOX_VE_ENDPOINT", "").strip().rstrip("/")
    token = os.getenv("PROXMOX_VE_API_TOKEN", "").strip()
    if not endpoint:
        raise ProxmoxAPIError("Proxmox endpoint is not configured")
    if not token:
        raise ProxmoxAPIError("Proxmox API token is not configured")

    insecure = os.getenv("PROXMOX_VE_INSECURE", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }
    if insecure:
        verify: bool | str = False
    else:
        ca_file = os.getenv("SSL_CERT_FILE", "").strip()
        verify = ca_file if ca_file and Path(ca_file).is_file() else True
    return endpoint, token, verify


def _client() -> httpx.Client:
    endpoint, token, verify = _settings()
    return httpx.Client(
        base_url=f"{endpoint}/api2/json",
        headers={"Authorization": f"PVEAPIToken={token}"},
        verify=verify,
        timeout=15.0,
    )


def _response_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text.strip()
    if isinstance(body, dict):
        message = str(body.get("message") or "").strip()
        if message:
            return message
        errors = body.get("errors")
        if errors:
            return str(errors)
    return ""


def _data(response: httpx.Response):
    try:
        response.raise_for_status()
    except httpx.HTTPError as exc:
        detail = _response_message(response)
        suffix = f": {detail}" if detail else ""
        raise ProxmoxAPIError(
            f"Proxmox API request failed ({response.status_code}){suffix}"
        ) from exc
    try:
        body = response.json()
    except ValueError as exc:
        raise ProxmoxAPIError("Proxmox API returned invalid JSON") from exc
    if not isinstance(body, dict) or "data" not in body:
        raise ProxmoxAPIError("Proxmox API returned an unexpected response")
    return body["data"]


def _size_gib(value: str) -> int | None:
    match = re.search(r"(?:^|,)size=([0-9.]+)([KMGT])(?:,|$)", value, re.I)
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2).upper()
    factor = {"K": 1 / (1024 * 1024), "M": 1 / 1024, "G": 1, "T": 1024}[unit]
    gib = amount * factor
    return int(gib) if gib.is_integer() else int(gib + 0.999999)


def _system_disk(config: dict) -> dict:
    disk_keys = []
    for key, value in config.items():
        if not re.fullmatch(r"(?:scsi|sata|virtio|ide)\d+", str(key)):
            continue
        text = str(value)
        if "media=cdrom" in text or "cloudinit" in text:
            continue
        disk_keys.append(str(key))

    boot = str(config.get("boot") or "")
    ordered = []
    if "order=" in boot:
        order = boot.split("order=", 1)[1].split(",", 1)[0]
        ordered = [item for item in order.split(";") if item in disk_keys]
    interface = (ordered or sorted(disk_keys))[0] if disk_keys else ""
    if not interface:
        return {"interface": "", "datastore": "", "size_gb": None, "raw": ""}

    raw = str(config.get(interface) or "")
    datastore = raw.split(":", 1)[0] if ":" in raw else ""
    return {
        "interface": interface,
        "datastore": datastore,
        "size_gb": disk["size_gb"] if False else _size_gib(raw),
        "raw": raw,
    }


def _template_details(client: httpx.Client, resource: dict) -> dict:
    node = str(resource.get("node") or "")
    vm_id = int(resource["vmid"])
    config = _data(client.get(f"/nodes/{node}/qemu/{vm_id}/config")) or {}
    disk = _system_disk(config)
    tags = [tag for tag in str(config.get("tags") or "").split(";") if tag]
    cores = int(config.get("cores") or 1)
    sockets = int(config.get("sockets") or 1)
    return {
        "vm_id": vm_id,
        "name": str(resource.get("name") or config.get("name") or f"VM {vm_id}"),
        "node": node,
        "status": str(resource.get("status") or "unknown"),
        "template": bool(int(resource.get("template") or 0)),
        "cpu": cores * sockets,
        "cores": cores,
        "sockets": sockets,
        "memory_mb": int(config.get("memory") or 0),
        "memory_gb": round(int(config.get("memory") or 0) / 1024, 2),
        "disk_interface": disk["interface"],
        "disk_datastore": disk["datastore"],
        "disk_gb": disk["size_gb"],
        "tags": tags,
        "boot": str(config.get("boot") or ""),
    }


def list_templates() -> list[dict]:
    """Return QEMU templates visible to the configured token with live metadata."""
    try:
        with _client() as client:
            resources = _data(client.get("/cluster/resources", params={"type": "vm"})) or []
            templates = [
                row for row in resources
                if row.get("type") == "qemu" and int(row.get("template") or 0) == 1
            ]
            return [
                _template_details(client, row)
                for row in sorted(templates, key=lambda item: (str(item.get("node")), int(item.get("vmid") or 0)))
            ]
    except httpx.HTTPError as exc:
        raise ProxmoxAPIError(f"Cannot reach Proxmox: {exc}") from exc


def inspect_template(vm_id: int) -> dict:
    """Resolve a VM ID to its current node/config and verify it is still a template."""
    with _client() as client:
        resources = _data(client.get("/cluster/resources", params={"type": "vm"})) or []
        resource = next(
            (
                row for row in resources
                if row.get("type") == "qemu" and int(row.get("vmid") or -1) == int(vm_id)
            ),
            None,
        )
        if resource is None:
            raise ProxmoxAPIError(f"VM {vm_id} was not found in Proxmox")
        details = _template_details(client, resource)
        if not details["template"]:
            raise ProxmoxAPIError(f"VM {vm_id} exists but is not a template")
        return details


def create_spice_vv(node: str, vm_id: int, title: str = "") -> str:
    """Request a fresh SPICE ticket and render the virt-viewer .vv payload.

    SPICE tickets are intentionally generated on demand. They are short-lived and
    must never be persisted in run artifacts or exposed through unauthenticated
    static files.
    """
    endpoint, _, _ = _settings()
    proxy_host = urlparse(endpoint).hostname or endpoint.split(":", 1)[0]
    with _client() as client:
        data = _data(client.post(
            f"/nodes/{node}/qemu/{int(vm_id)}/spiceproxy",
            data={"proxy": proxy_host},
        ))

    if not isinstance(data, dict):
        raise ProxmoxAPIError("Proxmox SPICE proxy returned an unexpected response")

    values = dict(data)
    values.setdefault("type", "spice")
    values.setdefault("delete-this-file", 1)
    values.setdefault("secure-attention", "Ctrl+Alt+Ins")
    values.setdefault("release-cursor", "Ctrl+Alt+R")
    values.setdefault("toggle-fullscreen", "Shift+F11")
    if title:
        values["title"] = title

    preferred_order = [
        "type", "title", "host", "proxy", "tls-port", "password", "ca",
        "host-subject", "secure-attention", "release-cursor",
        "toggle-fullscreen", "delete-this-file",
    ]
    ordered = preferred_order + sorted(key for key in values if key not in preferred_order)
    lines = ["[virt-viewer]"]
    for key in ordered:
        if key not in values or values[key] in (None, ""):
            continue
        value = str(values[key]).replace("\r", "").replace("\n", "\\n")
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"
