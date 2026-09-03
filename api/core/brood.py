"""Shared Brood -> Command target contract.

Brood spiders may provision through any backend, but downstream Command spiders
must not need to know which backend created the target. They consume this
structured metadata contract instead.
"""
from __future__ import annotations

from typing import Any

from core.types import Artifact, RunOutput

BROOD_TARGET_CONTRACT = "arachne.brood-target/v1"


class BroodContractError(ValueError):
    pass


def build_brood_target_metadata(
    *,
    name: str,
    target_id: str,
    target_type: str,
    os_name: str,
    arch: str,
    ip: str,
    connection: str,
    port: int,
    state: str,
    lifetime: str | None = None,
    backend_spider: str,
    backend_data: dict[str, Any] | None = None,
    credentials_ref: str | None = None,
) -> dict[str, Any]:
    endpoint = {"host": ip, "port": int(port)}
    access: dict[str, Any] = {
        "preferred": connection,
        "endpoints": {connection: endpoint},
    }
    if credentials_ref:
        access["credentials"] = {
            "type": "secret_ref",
            "ref": credentials_ref,
        }

    family = "windows" if os_name == "windows" else "linux"
    return {
        "contract": BROOD_TARGET_CONTRACT,
        "identity": {
            "name": name,
            "id": str(target_id),
            "kind": target_type,
        },
        "platform": {
            "os": os_name,
            "family": family,
            "arch": arch,
        },
        "network": {
            "primary_ip": ip,
            "addresses": [ip] if ip else [],
        },
        "access": access,
        "lifecycle": {
            "state": state,
            "ephemeral": lifetime is not None,
            "lifetime": lifetime,
        },
        "backend": {
            "spider": backend_spider,
            "data": dict(backend_data or {}),
        },
    }


def is_brood_target(artifact: Artifact) -> bool:
    return artifact.metadata.get("contract") == BROOD_TARGET_CONTRACT


def _golden_credentials_ref(metadata: dict[str, Any]) -> str:
    """Resolve the default target credential from the Golden Image profile.

    Legacy Brood spiders only expose the selected image key in flat metadata.
    Keeping the lookup here means all of them can inherit the image credential
    without knowing anything about the Secrets implementation.
    """
    image = str(metadata.get("image") or "").strip().lower()
    if not image:
        return ""
    try:
        from golden_images import get_profile
        profile = get_profile(image)
    except Exception:
        return ""
    if not profile:
        return ""
    return str(profile.get("credentials_ref") or "").strip().lower()


def normalize_brood_artifact(artifact: Artifact, *, spider_name: str = "") -> Artifact:
    """Upgrade an old flat provision artifact to Brood target v1 in-place."""
    if is_brood_target(artifact):
        return artifact

    md = artifact.metadata or {}
    ip = str(md.get("ip") or "")
    os_name = str(md.get("os") or "")
    connection = str(md.get("conn") or ("winrm" if os_name == "windows" else "ssh"))
    default_port = 5985 if connection == "winrm" else 22
    try:
        port = int(md.get("port") or default_port)
    except (TypeError, ValueError):
        port = default_port

    backend_data = {
        key: value
        for key, value in md.items()
        if key in {
            "image",
            "vm_id",
            "template_vm_id",
            "node_name",
            "template_node_name",
            "clone_datastore_id",
            "golden",
            "requested_resources",
        }
    }
    credentials_ref = str(md.get("credentials_ref") or "").strip().lower() or _golden_credentials_ref(md)
    if credentials_ref:
        md["credentials_ref"] = credentials_ref

    contract = build_brood_target_metadata(
        name=artifact.name,
        target_id=str(md.get("vm_id") or artifact.location or artifact.name),
        target_type=artifact.type or "target",
        os_name=os_name,
        arch=str(md.get("arch") or "x86_64"),
        ip=ip,
        connection=connection,
        port=port,
        state=str(md.get("state") or "ready"),
        lifetime=md.get("lifetime"),
        backend_spider=str(md.get("backend") or spider_name),
        backend_data=backend_data,
        credentials_ref=credentials_ref or None,
    )
    artifact.metadata = {**md, **contract}
    return artifact


def validate_brood_target(artifact: Artifact, *, require_address: bool = True) -> dict[str, Any]:
    if not isinstance(artifact, Artifact):
        raise BroodContractError("Brood target must be an Artifact")
    md = artifact.metadata or {}
    if md.get("contract") != BROOD_TARGET_CONTRACT:
        raise BroodContractError(
            f"Artifact {artifact.name!r} does not implement {BROOD_TARGET_CONTRACT}"
        )

    for key in ("identity", "platform", "network", "access", "lifecycle", "backend"):
        if not isinstance(md.get(key), dict):
            raise BroodContractError(f"Brood target is missing mapping metadata.{key}")

    preferred = str(md["access"].get("preferred") or "")
    endpoints = md["access"].get("endpoints")
    if not preferred or not isinstance(endpoints, dict) or not isinstance(endpoints.get(preferred), dict):
        raise BroodContractError("Brood target has no preferred access endpoint")

    endpoint = endpoints[preferred]
    if require_address and not endpoint.get("host"):
        raise BroodContractError("Brood target has no reachable host address yet")
    if endpoint.get("port") in (None, ""):
        raise BroodContractError("Brood target access endpoint has no port")
    return md


def preferred_endpoint(artifact: Artifact, *, require_address: bool = True) -> dict[str, Any]:
    md = validate_brood_target(artifact, require_address=require_address)
    protocol = str(md["access"]["preferred"])
    endpoint = dict(md["access"]["endpoints"][protocol])
    endpoint["protocol"] = protocol
    return endpoint


def artifact_output_key(artifact: Artifact) -> str:
    return f"{artifact.type}:{artifact.location}:{artifact.name}"


def brood_target_outputs(artifact: Artifact) -> list[RunOutput]:
    """Render-neutral output panels for a normalized Brood target."""
    md = validate_brood_target(artifact, require_address=False)
    identity = md["identity"]
    platform = md["platform"]
    lifecycle = md["lifecycle"]
    backend = md["backend"]
    access = md["access"]
    preferred = str(access.get("preferred") or "")
    endpoint = (access.get("endpoints") or {}).get(preferred) or {}
    credentials = access.get("credentials") or {}
    key = artifact_output_key(artifact)

    machine = RunOutput(
        kind="machine",
        title=str(identity.get("name") or artifact.name),
        data={
            "id": str(identity.get("id") or artifact.location),
            "kind": str(identity.get("kind") or artifact.type),
            "os": str(platform.get("os") or ""),
            "family": str(platform.get("family") or ""),
            "arch": str(platform.get("arch") or ""),
            "state": str(lifecycle.get("state") or ""),
            "lifetime": lifecycle.get("lifetime"),
            "backend": str(backend.get("spider") or ""),
        },
        artifact=artifact,
        metadata={"artifact_key": key},
    )

    access_links = []
    host = str(endpoint.get("host") or "")
    if host and preferred == "ssh":
        access_links.append({"label": "Open SSH", "href": f"ssh://{host}", "kind": "connect"})
    access_output = RunOutput(
        kind="access",
        title="Access",
        data={
            "host": host,
            "port": endpoint.get("port"),
            "connection": preferred,
            "credentials_ref": credentials.get("ref") if isinstance(credentials, dict) else None,
        },
        links=access_links,
        metadata={"artifact_key": key},
    )

    outputs = [machine, access_output]
    if backend.get("spider") == "tofu-proxmox" and artifact.type == "vm":
        outputs.append(RunOutput(
            kind="console",
            title="Console",
            data={
                "provider": "Proxmox",
                "protocol": "noVNC",
                "target_id": str(identity.get("id") or artifact.location),
            },
            links=[{
                "label": "Open VNC ↗",
                "href": "__arachne_vm_console__",
                "kind": "console",
            }],
            metadata={"artifact_key": key},
        ))
    return outputs


def command_target_vars(key: str, artifact: Artifact) -> list[tuple[str, str]]:
    """Translate a Brood artifact into stable scalar vars for Command spiders."""
    md = validate_brood_target(artifact)
    endpoint = preferred_endpoint(artifact)
    identity = md["identity"]
    platform = md["platform"]

    values = [
        (key, str(endpoint["host"])),
        (f"{key}_host", str(endpoint["host"])),
        (f"{key}_port", str(endpoint["port"])),
        (f"{key}_connection", str(endpoint["protocol"])),
        (f"{key}_name", str(identity.get("name") or artifact.name)),
        (f"{key}_id", str(identity.get("id") or artifact.location)),
        (f"{key}_kind", str(identity.get("kind") or artifact.type)),
        (f"{key}_os", str(platform.get("os") or "")),
        (f"{key}_family", str(platform.get("family") or "")),
        (f"{key}_arch", str(platform.get("arch") or "")),
    ]
    credentials = md["access"].get("credentials")
    if isinstance(credentials, dict) and credentials.get("ref"):
        values.append((f"{key}_credentials_ref", str(credentials["ref"])))
    return [(k, v) for k, v in values if v != ""]
