"""Persistent settings for the Ansible playbook repository connector."""
from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, inspect, text

from database import Base, SessionLocal, engine


def utcnow():
    return datetime.now(timezone.utc)


class AnsiblePlaybookSettings(Base):
    __tablename__ = "ansible_playbook_settings"

    id = Column(Integer, primary_key=True)
    repo_url = Column(String(1024), nullable=False, default="")
    default_ref = Column(String(255), nullable=False, default="main")
    subdir = Column(String(512), nullable=False, default="playbooks")
    cache_dir = Column(String(1024), nullable=False, default="/var/cache/arachne/playbooks")
    credentials_ref = Column(String(64), nullable=False, default="")
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


def ensure_schema() -> None:
    AnsiblePlaybookSettings.__table__.create(bind=engine, checkfirst=True)
    columns = {col["name"] for col in inspect(engine).get_columns("ansible_playbook_settings")}
    if "credentials_ref" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE ansible_playbook_settings ADD COLUMN credentials_ref VARCHAR(64) NOT NULL DEFAULT ''"))


def _env_defaults() -> dict[str, str]:
    return {
        "repo_url": os.getenv("ANSIBLE_PLAYBOOK_REPO_URL", "").strip(),
        "default_ref": os.getenv("ANSIBLE_PLAYBOOK_REPO_REF", "main").strip() or "main",
        "subdir": os.getenv("ANSIBLE_PLAYBOOK_REPO_SUBDIR", "playbooks").strip().strip("/"),
        "cache_dir": os.getenv("ANSIBLE_PLAYBOOK_CACHE_DIR", "/var/cache/arachne/playbooks").strip() or "/var/cache/arachne/playbooks",
        "credentials_ref": os.getenv("ANSIBLE_PLAYBOOK_CREDENTIALS_REF", "").strip(),
    }


def get_settings() -> dict[str, str]:
    ensure_schema()
    db = SessionLocal()
    try:
        row = db.query(AnsiblePlaybookSettings).order_by(AnsiblePlaybookSettings.id).first()
        if not row:
            return _env_defaults()
        return {
            "repo_url": row.repo_url or "",
            "default_ref": row.default_ref or "main",
            "subdir": row.subdir or "",
            "cache_dir": row.cache_dir or "/var/cache/arachne/playbooks",
            "credentials_ref": row.credentials_ref or "",
        }
    finally:
        db.close()


def save_settings(*, repo_url: str, default_ref: str, subdir: str, cache_dir: str, credentials_ref: str = "") -> dict[str, str]:
    ensure_schema()
    repo_url = str(repo_url or "").strip()
    default_ref = str(default_ref or "main").strip() or "main"
    subdir = str(subdir or "").strip().strip("/")
    cache_dir = str(cache_dir or "/var/cache/arachne/playbooks").strip()
    credentials_ref = str(credentials_ref or "").strip().lower()

    if not repo_url:
        raise ValueError("Repository URL is required")
    if not cache_dir:
        raise ValueError("Cache directory is required")

    db = SessionLocal()
    try:
        row = db.query(AnsiblePlaybookSettings).order_by(AnsiblePlaybookSettings.id).first()
        if row is None:
            row = AnsiblePlaybookSettings()
            db.add(row)
        row.repo_url = repo_url
        row.default_ref = default_ref
        row.subdir = subdir
        row.cache_dir = cache_dir
        row.credentials_ref = credentials_ref
        db.commit()
        return {
            "repo_url": row.repo_url,
            "default_ref": row.default_ref,
            "subdir": row.subdir,
            "cache_dir": row.cache_dir,
            "credentials_ref": row.credentials_ref,
        }
    finally:
        db.close()


ensure_schema()
