"""Admin UI for mapping human golden-image profiles to Proxmox templates."""
from __future__ import annotations

import asyncio

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth.deps import get_db, require_role
from golden_images import GoldenImageProfile, ensure_schema, validate_profile
from main import app, render
from proxmox_api import ProxmoxAPIError, inspect_template, list_templates
from secrets_store import list_credentials


ensure_schema()


def _profiles(db: Session) -> list[GoldenImageProfile]:
    return db.query(GoldenImageProfile).order_by(
        GoldenImageProfile.enabled.desc(), GoldenImageProfile.label, GoldenImageProfile.slug,
    ).all()


def _target_credentials() -> list[dict]:
    return [row for row in list_credentials() if row.get("kind") in {"ssh", "winrm"}]


@app.get("/admin/golden-images", response_class=HTMLResponse)
async def admin_golden_images(
    request: Request,
    user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    error = ""
    templates = []
    try:
        templates = await asyncio.to_thread(list_templates)
    except ProxmoxAPIError as exc:
        error = str(exc)

    template_by_id = {int(item["vm_id"]): item for item in templates}
    cards = []
    for row in _profiles(db):
        live = template_by_id.get(int(row.vm_id))
        cards.append({
            "id": row.id,
            "slug": row.slug,
            "label": row.label,
            "os": row.os,
            "vm_id": row.vm_id,
            "credentials_ref": row.credentials_ref or "",
            "enabled": row.enabled,
            "live": live,
            "healthy": bool(live),
        })

    return render(
        request,
        "admin/golden_images.html",
        user=user,
        profiles=cards,
        templates_available=templates,
        proxmox_error=error,
        target_credentials=_target_credentials(),
    )


@app.get("/api/admin/golden-images/credentials")
def admin_golden_image_credentials(user=Depends(require_role("admin"))):
    return {"credentials": _target_credentials()}


@app.post("/admin/golden-images/save")
async def admin_golden_images_save(
    request: Request,
    user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    form = await request.form()
    original_slug = str(form.get("original_slug") or "").strip().lower()
    try:
        slug, label, os_name, vm_id = validate_profile(
            slug=form.get("slug"),
            label=form.get("label"),
            os_name=form.get("os"),
            vm_id=form.get("vm_id"),
        )
        await asyncio.to_thread(inspect_template, vm_id)
    except (ValueError, ProxmoxAPIError) as exc:
        raise HTTPException(400, str(exc)) from exc

    credentials_ref = str(form.get("credentials_ref") or "").strip().lower()
    credentials = {row["slug"]: row for row in _target_credentials()}
    if credentials_ref:
        credential = credentials.get(credentials_ref)
        if not credential:
            raise HTTPException(400, f"Target credential '{credentials_ref}' not found")
        expected_kind = "winrm" if os_name == "windows" else "ssh"
        if credential.get("kind") != expected_kind:
            raise HTTPException(
                400,
                f"Golden image {os_name!r} requires a {expected_kind} credential, got {credential.get('kind')!r}",
            )

    row = None
    if original_slug:
        row = db.query(GoldenImageProfile).filter(GoldenImageProfile.slug == original_slug).first()
        if not row:
            raise HTTPException(404, "Golden image profile not found")

    conflict = db.query(GoldenImageProfile).filter(GoldenImageProfile.slug == slug).first()
    if conflict and (row is None or conflict.id != row.id):
        raise HTTPException(409, f"Profile '{slug}' already exists")

    if row is None:
        row = GoldenImageProfile(slug=slug, label=label, os=os_name, vm_id=vm_id)
        db.add(row)
    else:
        row.slug = slug
        row.label = label
        row.os = os_name
        row.vm_id = vm_id

    row.credentials_ref = credentials_ref or None
    row.enabled = "enabled" in form
    db.commit()
    return RedirectResponse("/admin/golden-images", status_code=303)


@app.post("/admin/golden-images/{slug}/delete")
def admin_golden_images_delete(
    slug: str,
    user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    row = db.query(GoldenImageProfile).filter(GoldenImageProfile.slug == slug).first()
    if row:
        db.delete(row)
        db.commit()
    return RedirectResponse("/admin/golden-images", status_code=303)
