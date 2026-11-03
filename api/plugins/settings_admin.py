"""Administrative configuration catalog, read-only startup values and live overrides."""
from __future__ import annotations

from urllib.parse import quote
import asyncio
import os
import signal

from fastapi import BackgroundTasks, HTTPException

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from auth.deps import require_administrator
from main import app, render
from settings_registry import (
    list_settings, set_override, reset_override, restart_is_pending,
    is_self_restart_available,
)


@app.get("/admin/settings", response_class=HTMLResponse)
def admin_settings(request: Request, user=Depends(require_administrator)):
    return render(
        request, "admin/settings.html", user=user,
        settings=list_settings(),
        restart_available=is_self_restart_available(),
        restart_pending=restart_is_pending(),
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
        return RedirectResponse("/admin/settings?error=" + quote(str(exc)) + "#settings-integrations",
                                status_code=303)
    return RedirectResponse("/admin/settings?saved=1", status_code=303)


@app.post("/admin/settings/reset")
async def admin_settings_reset(request: Request, user=Depends(require_administrator)):
    form = await request.form()
    try:
        reset_override(str(form.get("key") or ""), actor=user.username)
    except ValueError as exc:
        return RedirectResponse("/admin/settings?error=" + quote(str(exc)) + "#live",
                                status_code=303)
    return RedirectResponse("/admin/settings?saved=1#live", status_code=303)


async def _terminate_after_response() -> None:
    """Uvicorn PID 1 exits; Docker restart policy relaunches the container."""
    await asyncio.sleep(0.35)
    os.kill(os.getpid(), signal.SIGTERM)


@app.post("/admin/settings/restart", status_code=202)
async def admin_settings_restart(
    background_tasks: BackgroundTasks,
    user=Depends(require_administrator),
):
    if not is_self_restart_available():
        raise HTTPException(
            409, "Self-restart is unavailable. Enable it in Docker Compose or use just restart."
        )
    background_tasks.add_task(_terminate_after_response)
    return {"accepted": True, "detail": "Container restart requested"}
