"""Bind infrastructure services to credentials from Control -> Secrets.

Bindings store only credential references. Secret material remains in the selected
SecretProvider (Vault or encrypted DB). At runtime Arachne materializes the small
set of legacy environment variables still consumed by existing adapters. This is
a compatibility bridge: .env no longer owns those credentials.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String

from database import Base, SessionLocal, engine
from secrets_store import resolve_credential


SERVICE_SPECS = {
    "forgejo": {
        "label": "Forgejo",
        "kinds": {"token"},
        "env": {"FORGEJO_TOKEN": "token"},
    },
    "gitlab": {
        "label": "GitLab",
        "kinds": {"token"},
        "env": {"GITLAB_TOKEN": "token"},
    },
    "proxmox": {
        "label": "Proxmox VE",
        "kinds": {"token"},
        "env": {"PROXMOX_VE_API_TOKEN": "token"},
    },
    "nexus": {
        "label": "Nexus",
        "kinds": {"basic"},
        "env": {"NEXUS_USER": "username", "NEXUS_PASSWORD": "password"},
    },
}


def utcnow():
    return datetime.now(timezone.utc)


class ServiceCredentialBinding(Base):
    __tablename__ = "service_credential_bindings"

    id = Column(Integer, primary_key=True)
    service = Column(String(64), unique=True, nullable=False, index=True)
    credential_slug = Column(String(64), nullable=False, default="")
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


def ensure_schema() -> None:
    ServiceCredentialBinding.__table__.create(bind=engine, checkfirst=True)


def list_bindings() -> list[dict]:
    ensure_schema()
    db = SessionLocal()
    try:
        rows = {row.service: row.credential_slug for row in db.query(ServiceCredentialBinding).all()}
        return [
            {
                "service": key,
                "label": spec["label"],
                "credential": rows.get(key, ""),
                "kinds": sorted(spec["kinds"]),
            }
            for key, spec in SERVICE_SPECS.items()
        ]
    finally:
        db.close()


def get_binding(service: str) -> str:
    ensure_schema()
    service = str(service or "").strip().lower()
    if service not in SERVICE_SPECS:
        raise ValueError(f"unknown service credential binding: {service}")
    db = SessionLocal()
    try:
        row = db.query(ServiceCredentialBinding).filter(ServiceCredentialBinding.service == service).first()
        return row.credential_slug if row else ""
    finally:
        db.close()


def save_bindings(values: dict[str, str]) -> None:
    ensure_schema()
    db = SessionLocal()
    try:
        for service, spec in SERVICE_SPECS.items():
            slug = str(values.get(service) or "").strip().lower()
            if slug:
                credential = resolve_credential(slug)
                if credential.kind not in spec["kinds"]:
                    allowed = ", ".join(sorted(spec["kinds"]))
                    raise ValueError(
                        f"{spec['label']} requires credential type {allowed}, got {credential.kind}"
                    )
            row = db.query(ServiceCredentialBinding).filter(ServiceCredentialBinding.service == service).first()
            if row is None:
                row = ServiceCredentialBinding(service=service)
                db.add(row)
            row.credential_slug = slug
        db.commit()
    finally:
        db.close()
    apply_bound_credentials()


def _materialize(service: str, slug: str) -> dict[str, str]:
    spec = SERVICE_SPECS[service]
    credential = resolve_credential(slug)
    if credential.kind not in spec["kinds"]:
        raise RuntimeError(
            f"credential {slug!r} has type {credential.kind!r}, not valid for {service}"
        )

    result = {}
    for env_name, source in spec["env"].items():
        if source == "username":
            value = credential.username
        else:
            value = str(credential.values.get(source) or "")
        if not value:
            raise RuntimeError(f"credential {slug!r} has no {source!r} value required by {service}")
        result[env_name] = value
    return result


def apply_bound_credentials() -> dict[str, str]:
    """Materialize configured service credentials into the current process.

    Existing adapters still read conventional environment variable names. The
    values now originate in SecretProvider storage, not dotenv. Loaded modules
    with import-time constants are refreshed so GUI changes apply immediately.
    """
    ensure_schema()
    db = SessionLocal()
    try:
        rows = db.query(ServiceCredentialBinding).all()
        bindings = {row.service: row.credential_slug for row in rows if row.credential_slug}
    finally:
        db.close()

    materialized: dict[str, str] = {}
    for service, slug in bindings.items():
        if service not in SERVICE_SPECS:
            continue
        materialized.update(_materialize(service, slug))

    managed_names = {
        env_name
        for spec in SERVICE_SPECS.values()
        for env_name in spec["env"]
    }
    for name in managed_names:
        if name in materialized:
            os.environ[name] = materialized[name]
        else:
            os.environ.pop(name, None)

    # A few legacy modules cache env values at import time. Refresh those globals
    # without restarting Arachne after an admin changes a binding in the GUI.
    patches = {
        "input_sources": {"FORGEJO_TOKEN": "FORGEJO_TOKEN"},
        "plugins.spiders.forgejo": {"FORGEJO_TOKEN": "FORGEJO_TOKEN"},
        "plugins.spiders.gitlab": {"GITLAB_TOKEN": "GITLAB_TOKEN"},
    }
    for module_name, names in patches.items():
        module = sys.modules.get(module_name)
        if module is None:
            continue
        for attr, env_name in names.items():
            setattr(module, attr, os.environ.get(env_name, ""))

    return {service: slug for service, slug in bindings.items()}


ensure_schema()
