"""Secret providers and semantic credentials for Arachne.

Secrets can live in HashiCorp Vault KV v2 or in Arachne's encrypted database.
Provider bootstrap credentials are referenced from environment variables or
mounted files and are never stored as plaintext in PostgreSQL.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

from cryptography.fernet import Fernet, InvalidToken
import httpx
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from database import Base, SessionLocal, engine


_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
PROVIDER_KINDS = {"vault", "database"}
CREDENTIAL_KINDS = {"ssh", "winrm", "git-ssh", "git-token", "token", "basic"}


def utcnow():
    return datetime.now(timezone.utc)


class SecretProviderRow(Base):
    __tablename__ = "secret_providers"

    id = Column(Integer, primary_key=True)
    slug = Column(String(64), unique=True, nullable=False, index=True)
    label = Column(String(128), nullable=False)
    kind = Column(String(32), nullable=False, index=True)
    config_json = Column(Text, nullable=False, default="{}")
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class CredentialRow(Base):
    __tablename__ = "credentials"

    id = Column(Integer, primary_key=True)
    slug = Column(String(64), unique=True, nullable=False, index=True)
    label = Column(String(128), nullable=False)
    kind = Column(String(32), nullable=False, index=True)
    username = Column(String(255), nullable=False, default="")
    provider_id = Column(Integer, ForeignKey("secret_providers.id"), nullable=False, index=True)
    secret_ref = Column(String(512), nullable=False)
    metadata_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class EncryptedSecretRow(Base):
    __tablename__ = "encrypted_secrets"

    id = Column(Integer, primary_key=True)
    secret_ref = Column(String(512), unique=True, nullable=False, index=True)
    payload = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


def ensure_schema() -> None:
    SecretProviderRow.__table__.create(bind=engine, checkfirst=True)
    CredentialRow.__table__.create(bind=engine, checkfirst=True)
    EncryptedSecretRow.__table__.create(bind=engine, checkfirst=True)


def _json_load(raw: str | None) -> dict:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _validate_slug(value: str, what: str) -> str:
    value = str(value or "").strip().lower()
    if not _SLUG_RE.fullmatch(value):
        raise ValueError(f"{what} key must contain lowercase letters, digits, '.', '_' or '-'")
    return value


def _bootstrap_value(source: str, ref: str) -> str:
    source = str(source or "env").strip().lower()
    ref = str(ref or "").strip()
    if not ref:
        return ""
    if source == "env":
        return os.getenv(ref, "")
    if source == "file":
        try:
            return Path(ref).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(f"cannot read bootstrap secret file {ref!r}: {exc}") from exc
    raise RuntimeError(f"unsupported bootstrap secret source: {source}")


def _fernet() -> Fernet:
    source = os.getenv("ARACHNE_MASTER_KEY_SOURCE", "env").strip().lower()
    ref = os.getenv("ARACHNE_MASTER_KEY_REF", "ARACHNE_MASTER_KEY").strip()
    raw = _bootstrap_value(source, ref)
    if not raw:
        raise RuntimeError(
            "encrypted database secrets require ARACHNE_MASTER_KEY or configured master-key file"
        )
    key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode("utf-8")).digest())
    return Fernet(key)


@dataclass(frozen=True)
class ResolvedCredential:
    slug: str
    kind: str
    username: str
    values: dict[str, str]
    metadata: dict
    provider: str
    secret_ref: str


class SecretProvider:
    def get(self, ref: str) -> dict[str, str]:
        raise NotImplementedError

    def put(self, ref: str, values: dict[str, str]) -> None:
        raise NotImplementedError

    def delete(self, ref: str) -> None:
        raise NotImplementedError

    def test(self) -> dict:
        raise NotImplementedError


class DatabaseSecretProvider(SecretProvider):
    def get(self, ref: str) -> dict[str, str]:
        db = SessionLocal()
        try:
            row = db.query(EncryptedSecretRow).filter(EncryptedSecretRow.secret_ref == ref).first()
            if not row:
                return {}
            try:
                raw = _fernet().decrypt(row.payload.encode("ascii")).decode("utf-8")
            except InvalidToken as exc:
                raise RuntimeError("cannot decrypt database secret with current master key") from exc
            return {str(k): str(v) for k, v in _json_load(raw).items() if v is not None}
        finally:
            db.close()

    def put(self, ref: str, values: dict[str, str]) -> None:
        payload = _fernet().encrypt(json.dumps(values, ensure_ascii=False).encode("utf-8")).decode("ascii")
        db = SessionLocal()
        try:
            row = db.query(EncryptedSecretRow).filter(EncryptedSecretRow.secret_ref == ref).first()
            if row is None:
                row = EncryptedSecretRow(secret_ref=ref, payload=payload)
                db.add(row)
            else:
                row.payload = payload
            db.commit()
        finally:
            db.close()

    def delete(self, ref: str) -> None:
        db = SessionLocal()
        try:
            row = db.query(EncryptedSecretRow).filter(EncryptedSecretRow.secret_ref == ref).first()
            if row:
                db.delete(row)
                db.commit()
        finally:
            db.close()

    def test(self) -> dict:
        _fernet()
        return {"ok": True, "detail": "master key is available"}


class VaultSecretProvider(SecretProvider):
    def __init__(self, config: dict):
        self.address = str(config.get("address") or "").rstrip("/")
        self.mount = str(config.get("mount") or "secret").strip("/")
        self.base_path = str(config.get("base_path") or "arachne").strip("/")
        self.namespace = str(config.get("namespace") or "").strip()
        self.verify_tls = bool(config.get("verify_tls", True))
        self.mode = str(config.get("mode") or "read-write")
        self.auth_method = str(config.get("auth_method") or "token")
        self.config = config
        if not self.address:
            raise RuntimeError("Vault address is empty")

    def _headers(self) -> dict[str, str]:
        token = self._token()
        headers = {"X-Vault-Token": token}
        if self.namespace:
            headers["X-Vault-Namespace"] = self.namespace
        return headers

    def _token(self) -> str:
        if self.auth_method == "token":
            token = _bootstrap_value(
                self.config.get("token_source", "env"),
                self.config.get("token_ref", "VAULT_TOKEN"),
            )
            if not token:
                raise RuntimeError("Vault token bootstrap secret is empty")
            return token
        if self.auth_method == "approle":
            role_id = str(self.config.get("role_id") or "").strip()
            secret_id = _bootstrap_value(
                self.config.get("secret_id_source", "env"),
                self.config.get("secret_id_ref", "VAULT_SECRET_ID"),
            )
            if not role_id or not secret_id:
                raise RuntimeError("Vault AppRole role_id/secret_id is not configured")
            headers = {}
            if self.namespace:
                headers["X-Vault-Namespace"] = self.namespace
            with httpx.Client(verify=self.verify_tls, timeout=15) as client:
                response = client.post(
                    f"{self.address}/v1/auth/approle/login",
                    headers=headers,
                    json={"role_id": role_id, "secret_id": secret_id},
                )
            if response.status_code >= 400:
                raise RuntimeError(f"Vault AppRole login failed: {response.status_code} {response.text[:300]}")
            token = str((response.json().get("auth") or {}).get("client_token") or "")
            if not token:
                raise RuntimeError("Vault AppRole response did not contain client_token")
            return token
        raise RuntimeError(f"unsupported Vault auth method: {self.auth_method}")

    def _path(self, ref: str) -> str:
        ref = str(ref or "").strip().strip("/")
        if not ref or ".." in ref.split("/"):
            raise RuntimeError("invalid Vault secret reference")
        suffix = "/".join(part for part in [self.base_path, ref] if part)
        return f"{self.address}/v1/{self.mount}/data/{suffix}"

    def get(self, ref: str) -> dict[str, str]:
        with httpx.Client(verify=self.verify_tls, timeout=15) as client:
            response = client.get(self._path(ref), headers=self._headers())
        if response.status_code == 404:
            return {}
        if response.status_code >= 400:
            raise RuntimeError(f"Vault read failed: {response.status_code} {response.text[:300]}")
        data = ((response.json().get("data") or {}).get("data") or {})
        return {str(k): str(v) for k, v in data.items() if v is not None}

    def put(self, ref: str, values: dict[str, str]) -> None:
        if self.mode != "read-write":
            raise RuntimeError("Vault provider is read-only")
        with httpx.Client(verify=self.verify_tls, timeout=15) as client:
            response = client.post(self._path(ref), headers=self._headers(), json={"data": values})
        if response.status_code >= 400:
            raise RuntimeError(f"Vault write failed: {response.status_code} {response.text[:300]}")

    def delete(self, ref: str) -> None:
        if self.mode != "read-write":
            raise RuntimeError("Vault provider is read-only")
        with httpx.Client(verify=self.verify_tls, timeout=15) as client:
            response = client.delete(self._path(ref), headers=self._headers())
        if response.status_code >= 400 and response.status_code != 404:
            raise RuntimeError(f"Vault delete failed: {response.status_code} {response.text[:300]}")

    def test(self) -> dict:
        headers = self._headers()
        with httpx.Client(verify=self.verify_tls, timeout=15) as client:
            response = client.get(f"{self.address}/v1/sys/health", headers=headers)
        if response.status_code >= 500:
            raise RuntimeError(f"Vault health check failed: {response.status_code} {response.text[:300]}")
        return {"ok": True, "detail": f"Vault responded with HTTP {response.status_code}"}


def provider_instance(row: SecretProviderRow) -> SecretProvider:
    config = _json_load(row.config_json)
    if row.kind == "vault":
        return VaultSecretProvider(config)
    if row.kind == "database":
        return DatabaseSecretProvider()
    raise RuntimeError(f"unsupported secret provider kind: {row.kind}")


def list_providers() -> list[dict]:
    ensure_schema()
    db = SessionLocal()
    try:
        rows = db.query(SecretProviderRow).order_by(SecretProviderRow.label, SecretProviderRow.slug).all()
        return [{
            "id": row.id, "slug": row.slug, "label": row.label, "kind": row.kind,
            "enabled": row.enabled, "config": _json_load(row.config_json),
        } for row in rows]
    finally:
        db.close()


def get_provider(slug: str) -> dict | None:
    return next((row for row in list_providers() if row["slug"] == str(slug).strip().lower()), None)


def save_provider(*, original_slug: str = "", slug: str, label: str, kind: str, enabled: bool, config: dict) -> dict:
    ensure_schema()
    slug = _validate_slug(slug, "Provider")
    label = str(label or "").strip()
    kind = str(kind or "").strip().lower()
    if not label:
        raise ValueError("Provider name is required")
    if kind not in PROVIDER_KINDS:
        raise ValueError(f"Unsupported provider type: {kind}")
    db = SessionLocal()
    try:
        row = None
        if original_slug:
            row = db.query(SecretProviderRow).filter(SecretProviderRow.slug == original_slug).first()
        conflict = db.query(SecretProviderRow).filter(SecretProviderRow.slug == slug).first()
        if conflict and (row is None or conflict.id != row.id):
            raise ValueError(f"Provider '{slug}' already exists")
        if row is None:
            row = SecretProviderRow(slug=slug)
            db.add(row)
        row.slug, row.label, row.kind, row.enabled = slug, label, kind, bool(enabled)
        row.config_json = json.dumps(config, ensure_ascii=False)
        db.commit()
        return {"slug": row.slug, "label": row.label, "kind": row.kind}
    finally:
        db.close()


def _provider_row(db, slug: str) -> SecretProviderRow:
    row = db.query(SecretProviderRow).filter(
        SecretProviderRow.slug == str(slug).strip().lower(),
        SecretProviderRow.enabled.is_(True),
    ).first()
    if not row:
        raise ValueError(f"Secret provider '{slug}' not found or disabled")
    return row


def list_credentials() -> list[dict]:
    ensure_schema()
    db = SessionLocal()
    try:
        providers = {row.id: row.slug for row in db.query(SecretProviderRow).all()}
        rows = db.query(CredentialRow).order_by(CredentialRow.label, CredentialRow.slug).all()
        return [{
            "id": row.id, "slug": row.slug, "label": row.label, "kind": row.kind,
            "username": row.username, "provider": providers.get(row.provider_id, ""),
            "secret_ref": row.secret_ref, "metadata": _json_load(row.metadata_json),
        } for row in rows]
    finally:
        db.close()


def save_credential(*, original_slug: str = "", slug: str, label: str, kind: str, username: str, provider_slug: str, secret_ref: str, metadata: dict, secret_updates: dict[str, str]) -> dict:
    ensure_schema()
    slug = _validate_slug(slug, "Credential")
    label = str(label or "").strip()
    kind = str(kind or "").strip().lower()
    username = str(username or "").strip()
    secret_ref = str(secret_ref or f"credentials/{slug}").strip().strip("/")
    if not label:
        raise ValueError("Credential name is required")
    if kind not in CREDENTIAL_KINDS:
        raise ValueError(f"Unsupported credential type: {kind}")
    if not secret_ref or ".." in secret_ref.split("/"):
        raise ValueError("Invalid secret reference")

    db = SessionLocal()
    try:
        provider = _provider_row(db, provider_slug)
        row = None
        if original_slug:
            row = db.query(CredentialRow).filter(CredentialRow.slug == original_slug).first()
        conflict = db.query(CredentialRow).filter(CredentialRow.slug == slug).first()
        if conflict and (row is None or conflict.id != row.id):
            raise ValueError(f"Credential '{slug}' already exists")
        backend = provider_instance(provider)
        current = backend.get(secret_ref) if row is not None else {}
        merged = dict(current)
        merged.update({str(k): str(v) for k, v in secret_updates.items() if v not in (None, "")})
        if merged:
            backend.put(secret_ref, merged)
        if row is None:
            row = CredentialRow(slug=slug, provider_id=provider.id, secret_ref=secret_ref)
            db.add(row)
        row.slug, row.label, row.kind, row.username = slug, label, kind, username
        row.provider_id, row.secret_ref = provider.id, secret_ref
        row.metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
        db.commit()
        return {"slug": row.slug, "provider": provider.slug, "secret_ref": row.secret_ref}
    finally:
        db.close()


def resolve_credential(slug: str) -> ResolvedCredential:
    ensure_schema()
    db = SessionLocal()
    try:
        row = db.query(CredentialRow).filter(CredentialRow.slug == str(slug).strip().lower()).first()
        if not row:
            raise RuntimeError(f"credential {slug!r} not found")
        provider = db.query(SecretProviderRow).filter(SecretProviderRow.id == row.provider_id).first()
        if not provider or not provider.enabled:
            raise RuntimeError(f"credential {slug!r} secret provider is unavailable")
        values = provider_instance(provider).get(row.secret_ref)
        return ResolvedCredential(
            slug=row.slug, kind=row.kind, username=row.username, values=values,
            metadata=_json_load(row.metadata_json), provider=provider.slug, secret_ref=row.secret_ref,
        )
    finally:
        db.close()


def test_provider(slug: str) -> dict:
    ensure_schema()
    db = SessionLocal()
    try:
        provider = _provider_row(db, slug)
        return provider_instance(provider).test()
    finally:
        db.close()


ensure_schema()
