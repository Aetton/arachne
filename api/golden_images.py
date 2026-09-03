"""Golden image profile registry.

Profiles are human-facing names stored in PostgreSQL. They point at a Proxmox
VM ID and optionally a default target credential. Live node/storage/disk/hardware
facts are always discovered from Proxmox.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from database import Base, SessionLocal, engine


_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SUPPORTED_OS = {"redos7", "redos8", "windows"}


def utcnow():
    return datetime.now(timezone.utc)


class GoldenImageProfile(Base):
    __tablename__ = "golden_image_profiles"

    id = Column(Integer, primary_key=True)
    slug = Column(String(64), unique=True, nullable=False, index=True)
    label = Column(String(128), nullable=False)
    os = Column(String(32), nullable=False, index=True)
    backend = Column(String(32), default="proxmox", nullable=False)
    vm_id = Column(Integer, nullable=False)
    credentials_ref = Column(String(64), nullable=True, index=True)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


def ensure_schema() -> None:
    GoldenImageProfile.__table__.create(bind=engine, checkfirst=True)
    # Existing installations predate credentials_ref. create(checkfirst=True) does
    # not alter an existing table, so add the nullable column in-place.
    with engine.begin() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(golden_image_profiles)")} if engine.dialect.name == "sqlite" else set()
        if engine.dialect.name == "sqlite":
            if "credentials_ref" not in columns:
                conn.exec_driver_sql("ALTER TABLE golden_image_profiles ADD COLUMN credentials_ref VARCHAR(64)")
        elif engine.dialect.name == "postgresql":
            conn.exec_driver_sql("ALTER TABLE golden_image_profiles ADD COLUMN IF NOT EXISTS credentials_ref VARCHAR(64)")


def validate_profile(*, slug: str, label: str, os_name: str, vm_id) -> tuple[str, str, str, int]:
    slug = str(slug or "").strip().lower()
    label = str(label or "").strip()
    os_name = str(os_name or "").strip().lower()
    if not _SLUG_RE.fullmatch(slug):
        raise ValueError("Profile key must contain only lowercase letters, digits, '.', '_' or '-'")
    if not label:
        raise ValueError("Profile name is required")
    if os_name not in SUPPORTED_OS:
        raise ValueError(f"Unsupported OS profile: {os_name}")
    try:
        parsed_vm_id = int(vm_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Choose a Proxmox template") from exc
    if parsed_vm_id <= 0:
        raise ValueError("Choose a Proxmox template")
    return slug, label, os_name, parsed_vm_id


def get_profile(slug: str) -> dict | None:
    ensure_schema()
    db = SessionLocal()
    try:
        row = db.query(GoldenImageProfile).filter(
            GoldenImageProfile.slug == str(slug).strip().lower(),
            GoldenImageProfile.enabled.is_(True),
        ).first()
        if not row:
            return None
        return {
            "id": row.id,
            "slug": row.slug,
            "label": row.label,
            "os": row.os,
            "backend": row.backend,
            "vm_id": row.vm_id,
            "credentials_ref": row.credentials_ref or "",
            "enabled": row.enabled,
        }
    finally:
        db.close()


def list_profiles() -> list[dict]:
    ensure_schema()
    db = SessionLocal()
    try:
        rows = db.query(GoldenImageProfile).order_by(GoldenImageProfile.label, GoldenImageProfile.slug).all()
        return [
            {
                "id": row.id,
                "slug": row.slug,
                "label": row.label,
                "os": row.os,
                "backend": row.backend,
                "vm_id": row.vm_id,
                "credentials_ref": row.credentials_ref or "",
                "enabled": row.enabled,
            }
            for row in rows
        ]
    finally:
        db.close()


ensure_schema()
