"""Administrator UI for secret providers, credentials and service bindings."""
from __future__ import annotations

import os
from urllib.parse import quote

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from auth.deps import require_administrator
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


_DOTENV_IMPORTS = {
    "forgejo": {
        "label": "Forgejo service token",
        "slug": "forgejo-service",
        "kind": "token",
        "variables": ("FORGEJO_TOKEN",),
    },
    "gitlab": {
        "label": "GitLab service token",
        "slug": "gitlab-service",
        "kind": "token",
        "variables": ("GITLAB_TOKEN",),
    },
    "proxmox": {
        "label": "Proxmox VE API token",
        "slug": "proxmox-arachne",
        "kind": "token",
        "variables": ("PROXMOX_VE_API_TOKEN",),
    },
    "nexus": {
        "label": "Nexus upload credentials",
        "slug": "nexus-upload",
        "kind": "basic",
        "variables": ("NEXUS_USER", "NEXUS_PASSWORD"),
    },
}


def _checked(form, name: str) -> bool:
    return str(form.get(name) or "").lower() in {"1", "true", "on", "yes"}


def _dotenv_candidates() -> list[dict]:
    result = []
    for service, spec in _DOTENV_IMPORTS.items():
        present = [name for name in spec["variables"] if str(os.getenv(name, "")).strip()]
        missing = [name for name in spec["variables"] if name not in present]
        result.append({
            "service": service,
            "label": spec["label"],
            "slug": spec["slug"],
            "kind": spec["kind"],
            "variables": list(spec["variables"]),
            "present": present,
            "missing": missing,
            "ready": not missing,
        })
    return result


def _import_dotenv_service(service: str, provider_slug: str, existing: set[str]) -> str:
    spec = _DOTENV_IMPORTS[service]
    values = {name: str(os.getenv(name, "")) for name in spec["variables"]}
    missing = [name for name, value in values.items() if not value.strip()]
    if missing:
        raise ValueError(f"{service}: missing dotenv variable(s): {', '.join(missing)}")

    username = values.get("NEXUS_USER", "") if service == "nexus" else ""
    secret_updates = (
        {"password": values["NEXUS_PASSWORD"]}
        if service == "nexus"
        else {"token": values[spec["variables"][0]]}
    )
    slug = spec["slug"]
    save_credential(
        original_slug=slug if slug in existing else "",
        slug=slug,
        label=spec["label"],
        kind=spec["kind"],
        username=username,
        provider_slug=provider_slug,
        secret_ref=f"credentials/{slug}",
        metadata={"source": "dotenv-import"},
        secret_updates=secret_updates,
    )
    return slug


@app.get("/admin/secrets", response_class=HTMLResponse)
async def admin_secrets(request: Request, user=Depends(require_administrator)):
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


@app.get("/admin/secrets/import", response_class=HTMLResponse)
async def admin_secrets_import(request: Request, user=Depends(require_administrator)):
    return render(
        request,
        "admin/secrets_import.html",
        user=user,
        providers=[row for row in list_providers() if row.get("enabled")],
        candidates=_dotenv_candidates(),
        imported=request.query_params.get("imported", ""),
        error=request.query_params.get("error", ""),
    )


@app.post("/admin/secrets/import")
async def admin_secrets_import_apply(request: Request, user=Depends(require_administrator)):
    form = await request.form()
    provider_slug = str(form.get("provider") or "").strip().lower()
    selected = [str(value).strip().lower() for value in form.getlist("service")]
    selected = [service for service in selected if service in _DOTENV_IMPORTS]
    if not provider_slug:
        raise HTTPException(400, "Select a secret provider")
    if not selected:
        raise HTTPException(400, "Select at least one dotenv secret")

    existing = {row["slug"] for row in list_credentials()}
    imported: dict[str, str] = {}
    try:
        for service in selected:
            imported[service] = _import_dotenv_service(service, provider_slug, existing)
            existing.add(imported[service])
        current = {row["service"]: row.get("credential", "") for row in list_bindings()}
        current.update(imported)
        save_bindings(current)
    except (ValueError, RuntimeError) as exc:
        return RedirectResponse(
            f"/admin/secrets/import?error={quote(str(exc))}",
            status_code=303,
        )
    names = ", ".join(imported)
    return RedirectResponse(
        f"/admin/secrets/import?imported={quote(names)}",
        status_code=303,
    )


@app.post("/admin/secrets/providers/save")
async def admin_secret_provider_save(request: Request, user=Depends(require_administrator)):
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
def admin_secret_provider_test(slug: str, user=Depends(require_administrator)):
    try:
        result = test_provider(slug)
    except (ValueError, RuntimeError) as exc:
        return RedirectResponse(f"/admin/secrets?error={quote(str(exc))}", status_code=303)
    detail = str(result.get("detail") or "provider is healthy")
    return RedirectResponse(f"/admin/secrets?test=ok&detail={quote(detail)}", status_code=303)


@app.post("/admin/secrets/credentials/save")
async def admin_credential_save(request: Request, user=Depends(require_administrator)):
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
async def admin_secret_bindings_save(request: Request, user=Depends(require_administrator)):
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
