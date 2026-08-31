"""Authenticated VM console redirects for runtime Brood artifacts."""
from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.responses import RedirectResponse

from auth.deps import get_current_user
from database import Run, SessionLocal
from main import app
from proxmox_api import novnc_console_url


def _run_for_user(run_id: str, user):
    db = SessionLocal()
    try:
        run = db.get(Run, run_id)
        if not run:
            raise HTTPException(404, "Run not found")
        if "admin" not in (user.roles or []) and run.user_id != user.id:
            raise HTTPException(403, "Run is not available to this user")
        return {
            "id": run.id,
            "artifacts": list(run.artifacts or []),
        }
    finally:
        db.close()


def _vm_console_target(artifact: dict) -> tuple[str, int, str]:
    if artifact.get("type") != "vm":
        raise HTTPException(400, "Artifact is not a VM target")

    md = artifact.get("metadata") or {}
    backend = md.get("backend") or {}
    if not isinstance(backend, dict) or backend.get("spider") != "tofu-proxmox":
        raise HTTPException(400, "Artifact does not provide a Proxmox console")

    backend_data = backend.get("data") or {}
    identity = md.get("identity") or {}
    node = str(backend_data.get("node_name") or "").strip()
    vm_id = identity.get("id") or backend_data.get("vm_id") or artifact.get("location")
    try:
        vm_id = int(vm_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "VM artifact has no valid target id") from exc
    if not node:
        raise HTTPException(400, "VM artifact has no Proxmox node")
    return node, vm_id, str(artifact.get("name") or f"vm-{vm_id}")


@app.get("/runs/{run_id}/artifacts/{artifact_index}/console")
def open_vm_console(
    run_id: str,
    artifact_index: int,
    user=Depends(get_current_user),
):
    run = _run_for_user(run_id, user)
    artifacts = run["artifacts"]
    if artifact_index < 0 or artifact_index >= len(artifacts):
        raise HTTPException(404, "Artifact not found")

    node, vm_id, name = _vm_console_target(artifacts[artifact_index])
    return RedirectResponse(
        novnc_console_url(node, vm_id, name),
        status_code=302,
        headers={"Cache-Control": "no-store"},
    )
