"""Admin-only connection editor. Secrets remain in Control -> Secrets."""

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
import asyncio
import logging
from connection_tests import hypervisor

_logger = logging.getLogger(__name__)
from auth.deps import require_role
from main import app, render
from core.optional_plugins import installed_bundles
from infrastructure_connections import list_connections, save_connection
from secrets_store import list_credentials


@app.get("/admin/infrastructure")
def infrastructure(request: Request, user=Depends(require_role("admin"))):
    backends = sorted(
        n.removeprefix("tofu-") for n in installed_bundles() if n.startswith("tofu-")
    )
    return render(
        request,
        "admin/infrastructure.html",
        user=user,
        connections=list_connections(),
        backends=backends,
        credentials=[c for c in list_credentials() if c["kind"] in {"token", "basic"}],
    )


@app.post("/admin/infrastructure/save")
async def infrastructure_save(request: Request, user=Depends(require_role("admin"))):
    f = await request.form()
    backend = str(f.get("backend") or "")
    if f"tofu-{backend}" not in installed_bundles():
        raise HTTPException(400, "Install the corresponding tofu spider first")
    try:
        save_connection(
            slug=str(f.get("slug") or ""),
            label=str(f.get("label") or ""),
            backend=backend,
            endpoint=str(f.get("endpoint") or ""),
            credential_slug=str(f.get("credential_slug") or ""),
            insecure="insecure" in f,
            enabled="enabled" in f,
            ca_action=str(f.get("ca_action") or "keep"),
            ca_pem=str(f.get("ca_pem") or ""),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/admin/infrastructure", status_code=303)


@app.post("/api/admin/infrastructure/test")
async def infrastructure_test(request: Request, user=Depends(require_role("admin"))):
    form = await request.form()
    try:
        result = await asyncio.to_thread(
            hypervisor,
            str(form.get("backend") or ""),
            str(form.get("endpoint") or ""),
            str(form.get("credential_slug") or ""),
            "insecure" in form,
            slug=str(form.get("slug") or ""),
            ca_action=str(form.get("ca_action") or "keep"),
            ca_pem=str(form.get("ca_pem") or ""),
        )
        return result
    except (ValueError, RuntimeError) as exc:
        _logger.exception("Hypervisor connection test failed: backend=%s", form.get("backend"))
        return {"ok": False, "stage": "config", "detail": f"{type(exc).__name__}: verify endpoint and credential"}
    except Exception as exc:
        _logger.exception("Unexpected hypervisor connection test failure")
        return {"ok": False, "stage": "internal", "detail": f"Probe failed: {type(exc).__name__}; check API logs"}
