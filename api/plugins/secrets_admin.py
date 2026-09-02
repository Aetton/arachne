"""Admin UI for secret providers, credentials and service bindings."""
from __future__ import annotations

from urllib.parse import quote

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from auth.deps import require_role
from main import app, render
from service_credentials import list_bindings, save_bindings
from secrets_store import (
    CREDENTIAL_KINDS,
    PROVIDER_KINDS,
    list_credentials,
    list_providers,
    save_credential,
    save_provider,
    test_provider,
)


def _checked(form, name: str) -> bool:
    return str(form.get(name) or "").lower() in {"1", "true", "on", "yes"}


@app.get("/admin/secrets", response_class=HTMLResponse)
async def admin_secrets(request: Request, user=Depends(require_role("admin"))):
    return render(
        request,
        "admin/secrets.html",
        user=user,
        providers=list_providers(),
        credentials=list_credentials(),
        bindings=list_bindings(),
        provider_kinds=sorted(PROVIDER_KINDS),
        credential_kinds=sorted(CREDENTIAL_KINDS),
        saved=request.query_params.get("saved", ""),
        test_ok=request.query_params.get("test") == "ok",
        test_detail=request.query_params.get("detail", ""),
        test_error=request.query_params.get("error", ""),
    )


@app.post("/admin/secrets/providers/save")
async def admin_secret_provider_save(request: Request, user=Depends(require_role("admin"))):
    form = await request.form()
    kind = str(form.get("kind") or "vault").strip().lower()
    config = {}
    if kind == "vault":
        config = {
            "address": str(form.get("address") or "").strip(),
            "namespace": str(form.get("namespace") or "").strip(),
            "mount": str(form.get("mount") or "secret").strip() or "secret",
            "base_path": str(form.get("base_path") or "arachne").strip() or "arachne",
            "verify_tls": _checked(form, "verify_tls"),
            "mode": str(form.get("mode") or "read-write").strip(),
            "auth_method": str(form.get("auth_method") or "token").strip(),
            "token_source": str(form.get("token_source") or "env").strip(),
            "token_ref": str(form.get("token_ref") or "VAULT_TOKEN").strip(),
            "role_id": str(form.get("role_id") or "").strip(),
            "secret_id_source": str(form.get("secret_id_source") or "env").strip(),
            "secret_id_ref": str(form.get("secret_id_ref") or "VAULT_SECRET_ID").strip(),
        }
    elif kind == "database":
        config = {}
    try:
        result = save_provider(
            original_slug=str(form.get("original_slug") or "").strip().lower(),
            slug=form.get("slug"),
            label=form.get("label"),
            kind=kind,
            enabled=_checked(form, "enabled"),
            config=config,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/admin/secrets?saved={quote('provider:' + result['slug'])}", status_code=303)


@app.post("/admin/secrets/providers/{slug}/test")
def admin_secret_provider_test(slug: str, user=Depends(require_role("admin"))):
    try:
        result = test_provider(slug)
    except (ValueError, RuntimeError) as exc:
        return RedirectResponse(f"/admin/secrets?error={quote(str(exc))}", status_code=303)
    detail = str(result.get("detail") or "provider is healthy")
    return RedirectResponse(f"/admin/secrets?test=ok&detail={quote(detail)}", status_code=303)


@app.post("/admin/secrets/credentials/save")
async def admin_credential_save(request: Request, user=Depends(require_role("admin"))):
    form = await request.form()
    secret_updates = {
        "private_key": str(form.get("private_key") or ""),
        "password": str(form.get("password") or ""),
        "token": str(form.get("token") or ""),
        "known_hosts": str(form.get("known_hosts") or ""),
    }
    metadata = {
        "port": str(form.get("port") or "").strip(),
        "connection": str(form.get("connection") or "").strip(),
    }
    try:
        result = save_credential(
            original_slug=str(form.get("original_slug") or "").strip().lower(),
            slug=form.get("slug"),
            label=form.get("label"),
            kind=form.get("kind"),
            username=form.get("username"),
            provider_slug=form.get("provider"),
            secret_ref=form.get("secret_ref"),
            metadata=metadata,
            secret_updates=secret_updates,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/admin/secrets?saved={quote('credential:' + result['slug'])}", status_code=303)


@app.post("/admin/secrets/bindings/save")
async def admin_secret_bindings_save(request: Request, user=Depends(require_role("admin"))):
    form = await request.form()
    try:
        save_bindings({
            "forgejo": str(form.get("forgejo") or ""),
            "gitlab": str(form.get("gitlab") or ""),
            "proxmox": str(form.get("proxmox") or ""),
            "nexus": str(form.get("nexus") or ""),
        })
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/admin/secrets?saved=bindings", status_code=303)
