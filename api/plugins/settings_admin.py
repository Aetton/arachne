"""Administrative configuration catalog, read-only startup values and live overrides."""
from __future__ import annotations

from urllib.parse import quote

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from auth.deps import require_administrator
from main import app, render
from settings_registry import list_settings, set_override, reset_override


@app.get("/admin/settings", response_class=HTMLResponse)
def admin_settings(request: Request, user=Depends(require_administrator)):
    return render(
        request, "admin/settings.html", user=user,
        settings=list_settings(),
        saved=request.query_params.get("saved") == "1",
        error=request.query_params.get("error", ""),
    )


@app.post("/admin/settings/set")
async def admin_settings_save(request: Request, user=Depends(require_administrator)):
    form = await request.form()
    try:
        set_override(str(form.get("key") or ""), str(form.get("value") or ""),
                     actor=user.username)
    except ValueError as exc:
        return RedirectResponse("/admin/settings?error=" + quote(str(exc)) + "#live",
                                status_code=303)
    return RedirectResponse("/admin/settings?saved=1#live", status_code=303)


@app.post("/admin/settings/reset")
async def admin_settings_reset(request: Request, user=Depends(require_administrator)):
    form = await request.form()
    try:
        reset_override(str(form.get("key") or ""), actor=user.username)
    except ValueError as exc:
        return RedirectResponse("/admin/settings?error=" + quote(str(exc)) + "#live",
                                status_code=303)
    return RedirectResponse("/admin/settings?saved=1#live", status_code=303)
