"""Admin UI for the Ansible playbook repository connector."""
from __future__ import annotations

import asyncio

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from auth.deps import require_role
from core.playbook_repository import PlaybookRepository, PlaybookRepositoryError
from main import app, render
from playbook_settings import get_settings, save_settings


def _repository_from_values(repo_url: str, default_ref: str, subdir: str, cache_dir: str) -> PlaybookRepository:
    return PlaybookRepository(
        repo_url,
        default_ref=default_ref,
        subdir=subdir,
        cache_dir=cache_dir,
    )


@app.get("/admin/ansible", response_class=HTMLResponse)
async def admin_ansible(
    request: Request,
    user=Depends(require_role("admin")),
):
    return render(
        request,
        "admin/ansible_settings.html",
        user=user,
        settings=get_settings(),
        saved=request.query_params.get("saved") == "1",
        test_ok=request.query_params.get("test") == "ok",
        test_sha=request.query_params.get("sha", ""),
        test_error=request.query_params.get("error", ""),
    )


@app.post("/admin/ansible/save")
async def admin_ansible_save(
    request: Request,
    user=Depends(require_role("admin")),
):
    form = await request.form()
    try:
        save_settings(
            repo_url=form.get("repo_url"),
            default_ref=form.get("default_ref"),
            subdir=form.get("subdir"),
            cache_dir=form.get("cache_dir"),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/admin/ansible?saved=1", status_code=303)


@app.post("/admin/ansible/test")
async def admin_ansible_test(
    request: Request,
    user=Depends(require_role("admin")),
):
    form = await request.form()
    repo_url = str(form.get("repo_url") or "").strip()
    default_ref = str(form.get("default_ref") or "main").strip() or "main"
    subdir = str(form.get("subdir") or "").strip().strip("/")
    cache_dir = str(form.get("cache_dir") or "/var/cache/arachne/playbooks").strip()

    repository = _repository_from_values(repo_url, default_ref, subdir, cache_dir)
    try:
        result = await asyncio.to_thread(repository.probe)
    except PlaybookRepositoryError as exc:
        return render(
            request,
            "admin/ansible_settings.html",
            user=user,
            settings={
                "repo_url": repo_url,
                "default_ref": default_ref,
                "subdir": subdir,
                "cache_dir": cache_dir,
            },
            saved=False,
            test_ok=False,
            test_sha="",
            test_error=str(exc),
            status_code=400,
        )

    return render(
        request,
        "admin/ansible_settings.html",
        user=user,
        settings={
            "repo_url": repo_url,
            "default_ref": default_ref,
            "subdir": subdir,
            "cache_dir": cache_dir,
        },
        saved=False,
        test_ok=True,
        test_sha=result["sha"],
        test_error="",
    )
