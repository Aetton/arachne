"""Named infrastructure endpoints. Only secret references are persisted here."""

from __future__ import annotations
import os
import re
import ssl
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from sqlalchemy import Column, String, Boolean, Text
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
    ca_pem = Column(Text, nullable=False, default="")


def ensure_schema():
    InfrastructureConnection.__table__.create(bind=engine, checkfirst=True)


def list_connections():
    ensure_schema()
    with SessionLocal() as db:
        return [
            {
                **{
                    k: getattr(r, k)
                    for k in (
                        "slug", "label", "backend", "endpoint",
                        "credential_slug", "insecure", "enabled",
                    )
                },
                "has_ca": bool(r.ca_pem),
            }
            for r in db.query(InfrastructureConnection)
            .order_by(InfrastructureConnection.slug)
            .all()
        ]


def _validate_ca_pem(value: str) -> str:
    """Validate a PEM CA bundle without changing global trust."""
    value = str(value or "").strip()
    if not value:
        raise ValueError("CA certificate cannot be empty")
    if len(value.encode("utf-8")) > 131072:
        raise ValueError("CA bundle is too large (128 KiB max)")
    if "PRIVATE KEY" in value or "BEGIN CERTIFICATE" not in value:
        raise ValueError("Provide PEM certificates only, never private keys")
    try:
        ssl.create_default_context(cadata=value)
    except (ssl.SSLError, ValueError) as exc:
        raise ValueError("Invalid PEM CA certificate bundle") from exc
    return value + "\n"


def get_ca_pem(slug: str, backend: str) -> str:
    """Internal server-side CA lookup; never expose PEM in list_connections()."""
    ensure_schema()
    with SessionLocal() as db:
        row = db.get(InfrastructureConnection, slug)
        if not row or row.backend != backend:
            raise ValueError("Hypervisor connection not found")
        return row.ca_pem or ""


def tls_verify(insecure: bool, ca_pem: str = "", *, ovirt: bool = False):
    if insecure:
        return False
    if ca_pem:
        context = ssl.create_default_context()
        context.load_verify_locations(cadata=_validate_ca_pem(ca_pem))
        return context
    ca_file = os.getenv("SSL_CERT_FILE", "").strip()
    if ovirt:
        return ssl.create_default_context(cafile=ca_file or None)
    return ca_file if ca_file and Path(ca_file).is_file() else True


def _ca_file(slug: str, ca_pem: str) -> str:
    """Provide an on-demand CA file for OpenTofu without touching system CA."""
    import hashlib
    directory = Path(tempfile.gettempdir()) / f"arachne-ca-{os.getuid()}"
    directory.mkdir(mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    filename = hashlib.sha256(slug.encode("utf-8")).hexdigest() + ".pem"
    target = directory / filename
    import secrets
    temp = directory / (filename + "." + secrets.token_hex(8) + ".tmp")
    try:
        with temp.open("x", encoding="utf-8") as handle:
            os.chmod(temp, 0o600)
            handle.write(ca_pem)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return str(target)


def get_connection(slug, backend, *, require_enabled=True):
    connection = next((c for c in list_connections() if c["slug"] == slug), None)
    if not connection or connection["backend"] != backend:
        raise ValueError(f"Unknown {backend} connection: {slug!r}")
    if require_enabled and not connection["enabled"]:
        raise ValueError(f"Connection {slug!r} is disabled for provisioning")
    return connection


def save_connection(
    *, slug, label, backend, endpoint, credential_slug, insecure=False, enabled=True,\n    ca_action="keep", ca_pem=""
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
        if row and row.backend != backend:
            raise ValueError("Connection backend is immutable; create a new connection key")
        if ca_action not in {"keep", "replace", "clear"}:
            raise ValueError("Invalid CA action")
        if ca_action == "replace":
            new_ca = _validate_ca_pem(ca_pem)
        elif ca_action == "clear":
            new_ca = ""
        else:
            new_ca = row.ca_pem if row else ""
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
            ca_pem=new_ca,
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
    ca_pem = get_ca_pem(slug, backend)
    ca_file = _ca_file(slug, ca_pem) if ca_pem else os.getenv("SSL_CERT_FILE", "")
    secret = resolve_credential(c["credential_slug"])
    if backend == "proxmox":
        if secret.kind != "token" or not secret.values.get("token"):
            raise ValueError("Proxmox connection requires a nonempty token")
        return {
            "PROXMOX_VE_ENDPOINT": c["endpoint"],
            "PROXMOX_VE_API_TOKEN": str(secret.values["token"]),
            "PROXMOX_VE_INSECURE": str(c["insecure"]).lower(),
            "SSL_CERT_FILE": ca_file,
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
