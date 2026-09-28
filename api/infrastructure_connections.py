"""Named infrastructure endpoints. Only secret references are persisted here."""

from __future__ import annotations
import os
import re
from urllib.parse import urlsplit
from sqlalchemy import Column, String, Boolean
from database import Base, SessionLocal, engine
from secrets_store import resolve_credential


class InfrastructureConnection(Base):
    __tablename__ = "infrastructure_connections"
    slug = Column(String(64), primary_key=True)
    label = Column(String(128), nullable=False)
    backend = Column(String(32), nullable=False)
    endpoint = Column(String(512), nullable=False)
    credential_slug = Column(String(64), nullable=False)
    insecure = Column(Boolean, nullable=False, default=False)
    enabled = Column(Boolean, nullable=False, default=True)


def ensure_schema():
    InfrastructureConnection.__table__.create(bind=engine, checkfirst=True)


def list_connections():
    ensure_schema()
    with SessionLocal() as db:
        return [
            {
                k: getattr(r, k)
                for k in (
                    "slug",
                    "label",
                    "backend",
                    "endpoint",
                    "credential_slug",
                    "insecure",
                    "enabled",
                )
            }
            for r in db.query(InfrastructureConnection)
            .order_by(InfrastructureConnection.slug)
            .all()
        ]


def get_connection(slug, backend, *, require_enabled=True):
    connection = next((c for c in list_connections() if c["slug"] == slug), None)
    if not connection or connection["backend"] != backend:
        raise ValueError(f"Unknown {backend} connection: {slug!r}")
    if require_enabled and not connection["enabled"]:
        raise ValueError(f"Connection {slug!r} is disabled for provisioning")
    return connection


def save_connection(
    *, slug, label, backend, endpoint, credential_slug, insecure=False, enabled=True
):
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", slug or ""):
        raise ValueError("Invalid connection key")
    if backend not in {"proxmox", "ovirt"} or not label.strip():
        raise ValueError("Backend and label are required")
    url = urlsplit(endpoint)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError(
            "Use an HTTPS API URL without embedded credentials, query or fragment"
        )
    credential = resolve_credential(credential_slug)
    expected = "token" if backend == "proxmox" else "basic"
    if credential.kind != expected:
        raise ValueError(f"{backend} requires a {expected} credential")
    ensure_schema()
    with SessionLocal() as db:
        row = db.get(InfrastructureConnection, slug)
        if row and (
            row.endpoint.rstrip("/") != endpoint.rstrip("/") or row.backend != backend
        ):
            raise ValueError(
                "Endpoint and backend are immutable; create a new connection key"
            )
        if not row:
            row = InfrastructureConnection(slug=slug)
            db.add(row)
        for k, v in dict(
            label=label.strip(),
            backend=backend,
            endpoint=endpoint.rstrip("/"),
            credential_slug=credential_slug,
            insecure=insecure,
            enabled=enabled,
        ).items():
            setattr(row, k, v)
        db.commit()


def execution_env(slug, backend):
    """Return per-child env only. Never mutate os.environ or persist secret values."""
    if not slug:
        if backend != "proxmox":
            raise ValueError("An oVirt connection is required")
        return {}  # Legacy endpoint/token compatibility.
    c = get_connection(slug, backend, require_enabled=False)
    secret = resolve_credential(c["credential_slug"])
    if backend == "proxmox":
        if secret.kind != "token" or not secret.values.get("token"):
            raise ValueError("Proxmox connection requires a nonempty token")
        return {
            "PROXMOX_VE_ENDPOINT": c["endpoint"],
            "PROXMOX_VE_API_TOKEN": str(secret.values["token"]),
            "PROXMOX_VE_INSECURE": str(c["insecure"]).lower(),
        }
    if (
        secret.kind != "basic"
        or not secret.username
        or not secret.values.get("password")
    ):
        raise ValueError("oVirt connection requires a username and password")
    return {
        "TF_VAR_ovirt_url": c["endpoint"],
        "TF_VAR_ovirt_username": secret.username,
        "TF_VAR_ovirt_password": str(secret.values["password"]),
        "TF_VAR_ovirt_insecure": str(c["insecure"]).lower(),
        "TF_VAR_ovirt_ca_file": os.getenv("SSL_CERT_FILE", ""),
    }
