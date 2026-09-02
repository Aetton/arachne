"""Admin UI and repository metadata API for the Ansible connector."""
from __future__ import annotations

import asyncio

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from auth.deps import require_administrator
from core.playbook_repository import PlaybookRepository, PlaybookRepositoryError
from main import app, render
from playbook_settings import get_settings, save_settings
from secrets_store import list_credentials


def _git_credentials() -> list[dict]:
    return [row for row in list_credentials() if row.get("kind") in {"git-ssh", "git-token"}]


def _repository_from_values(repo_url: str, default_ref: str, subdir: str, cache_dir: str, credentials_ref: str = "") -> PlaybookRepository:
    return PlaybookRepository(repo_url, default_ref=default_ref, subdir=subdir, cache_dir=cache_dir, credentials_ref=credentials_ref)


def _configured_repository() -> PlaybookRepository:
    settings = get_settings()
    repo_url = str(settings.get("repo_url") or "").strip()
    if not repo_url:
        raise HTTPException(409, "Ansible playbook repository is not configured")
    return _repository_from_values(
        repo_url,
        str(settings.get("default_ref") or "main"),
        str(settings.get("subdir") or ""),
        str(settings.get("cache_dir") or "/var/cache/arachne/playbooks"),
        str(settings.get("credentials_ref") or ""),
    )


def _render(request: Request, user, settings: dict, **extra):
    return render(request, "admin/ansible_settings.html", user=user, settings=settings, git_credentials=_git_credentials(), **extra)


@app.get("/admin/ansible", response_class=HTMLResponse)
async def admin_ansible(request: Request, user=Depends(require_administrator)):
    return _render(
        request, user, get_settings(),
        saved=request.query_params.get("saved") == "1",
        test_ok=request.query_params.get("test") == "ok",
        test_sha=request.query_params.get("sha", ""),
        test_error=request.query_params.get("error", ""),
    )


@app.post("/admin/ansible/save")
async def admin_ansible_save(request: Request, user=Depends(require_administrator)):
    form = await request.form()
    try:
        save_settings(
            repo_url=form.get("repo_url"), default_ref=form.get("default_ref"),
            subdir=form.get("subdir"), cache_dir=form.get("cache_dir"),
            credentials_ref=form.get("credentials_ref"),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/admin/ansible?saved=1", status_code=303)


@app.post("/admin/ansible/test")
async def admin_ansible_test(request: Request, user=Depends(require_administrator)):
    form = await request.form()
    settings = {
        "repo_url": str(form.get("repo_url") or "").strip(),
        "default_ref": str(form.get("default_ref") or "main").strip() or "main",
        "subdir": str(form.get("subdir") or "").strip().strip("/"),
        "cache_dir": str(form.get("cache_dir") or "/var/cache/arachne/playbooks").strip(),
        "credentials_ref": str(form.get("credentials_ref") or "").strip().lower(),
    }
    repository = _repository_from_values(**settings)
    try:
        result = await asyncio.to_thread(repository.probe)
    except PlaybookRepositoryError as exc:
        return _render(request, user, settings, saved=False, test_ok=False, test_sha="", test_error=str(exc))
    return _render(request, user, settings, saved=False, test_ok=True, test_sha=result["sha"], test_error="")


@app.get("/api/admin/ansible/refs")
async def admin_ansible_refs(user=Depends(require_administrator)):
    repository = _configured_repository()
    try:
        refs = await asyncio.to_thread(repository.list_refs)
    except PlaybookRepositoryError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"repo": repository.repo_url, "default_ref": repository.default_ref, "refs": refs}


@app.get("/api/admin/ansible/playbooks")
async def admin_ansible_playbooks(ref: str | None = None, user=Depends(require_administrator)):
    repository = _configured_repository()
    try:
        return await asyncio.to_thread(repository.list_playbooks, ref=ref)
    except PlaybookRepositoryError as exc:
        raise HTTPException(502, str(exc)) from exc
