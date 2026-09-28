"""Admin-only connection editor. Secrets remain in Control -> Secrets."""

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
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
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/admin/infrastructure", status_code=303)
