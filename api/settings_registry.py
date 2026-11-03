"""Central catalog of Arachne configuration.

Only explicitly supported live numeric settings may be overridden in the DB.
Bootstrap secrets, process startup settings and build flags are inventory-only.
"""
from __future__ import annotations

import logging
import os
import time
import re
from urllib.parse import urlsplit
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String, Text

from database import Base, SessionLocal

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SettingSpec:
    key: str
    group: str
    label: str
    default: str
    mode: str = "restart"   # live, restart, bootstrap, build
    description: str = ""
    minimum: float | None = None
    maximum: float | None = None
    secret: bool = False


SPECS = (
    SettingSpec("INPUT_SOURCE_CACHE_TTL", "Performance", "TTL кэша веток", "30",
                "live", "Секунды хранения списка веток Forgejo", 0, 3600),
    SettingSpec("FORGEJO_POLL_INTERVAL", "Performance", "Интервал опроса Forgejo", "2",
                "live", "Секунды между запросами статуса Actions", 0.5, 300),
    SettingSpec("FORGEJO_DEADLINE", "Performance", "Максимальное время Forgejo", "3600",
                "live", "Таймаут новых сборок, секунды", 60, 86400),
    SettingSpec("GITLAB_POLL_INTERVAL", "Performance", "Интервал опроса GitLab", "2",
                "live", "Секунды между запросами статуса pipeline", 0.5, 300),
    SettingSpec("GITLAB_DEADLINE", "Performance", "Максимальное время GitLab", "3600",
                "live", "Таймаут новых pipeline, секунды", 60, 86400),
    SettingSpec("KOJI_POLL_INTERVAL", "Performance", "Интервал опроса Koji", "2",
                "live", "Секунды между опросами Koji", 0.5, 300),
    SettingSpec("FORGEJO_URL", "Integrations", "Forgejo URL", "", "restart", "Адрес сервиса"),
    SettingSpec("FORGEJO_OWNER", "Integrations", "Владелец Forgejo", "example", "restart"),
    SettingSpec("FORGEJO_VERIFY_TLS", "Integrations", "Проверка TLS Forgejo", "true", "restart"),
    SettingSpec("GITLAB_URL", "Integrations", "GitLab URL", "", "restart"),
    SettingSpec("GITLAB_VERIFY_TLS", "Integrations", "Проверка TLS GitLab", "true", "restart"),
    SettingSpec("NEXUS_URL", "Integrations", "Nexus URL", "", "restart"),
    SettingSpec("KOJI_PROFILE", "Integrations", "Профиль Koji", "koji", "restart"),
    SettingSpec("ARACHNE_URL", "Integrations", "Внешний URL Арахны", "", "restart"),
    SettingSpec("PROXMOX_VE_ENDPOINT", "Integrations", "Legacy Proxmox URL", "", "restart",
                "Предпочтительнее задавать в Control → Гипервизоры"),
    SettingSpec("PROXMOX_VE_INSECURE", "Integrations", "Legacy Proxmox TLS", "false", "restart"),
    SettingSpec("ANSIBLE_PLAYBOOK_REPO_URL", "Ansible", "Bootstrap Git URL", "", "restart",
                "После первой настройки управляется в разделе Ansible"),
    SettingSpec("ANSIBLE_PLAYBOOK_REPO_REF", "Ansible", "Bootstrap Git ref", "main", "restart"),
    SettingSpec("ANSIBLE_PLAYBOOK_REPO_SUBDIR", "Ansible", "Bootstrap подкаталог", "playbooks/arachne", "restart"),
    SettingSpec("ANSIBLE_PLAYBOOK_CACHE_DIR", "Ansible", "Каталог кэша", "/var/cache/arachne/playbooks", "restart"),
    SettingSpec("ANSIBLE_PLAYBOOK_CREDENTIALS_REF", "Ansible", "Bootstrap credential", "", "restart"),
    SettingSpec("BUS_BACKEND", "Core", "Транспорт шины", "inmemory", "restart",
                "Изменение требует пересоздания соединений и перезапуска API"),
    SettingSpec("NATS_URL", "Core", "NATS URL", "nats://nats:4222", "restart"),
    SettingSpec("ENV", "Core", "Профиль окружения", "dev", "bootstrap"),
    SettingSpec("SCENARIOS_CONFIG", "Core", "Файл первоначального импорта сценариев", "config/scenarios.yaml", "restart"),
    SettingSpec("TOFU_ROOT", "OpenTofu", "Путь к модулям OpenTofu", "/app/tofu", "restart"),
    SettingSpec("TOFU_STATE_ROOT", "OpenTofu", "Путь к state", "/var/lib/arachne/tofu-state", "restart"),
    SettingSpec("TOFU_PROVIDER_MIRROR", "OpenTofu", "Зеркало провайдеров", "", "restart"),
    SettingSpec("TOFU_DEV_FALLBACK", "OpenTofu", "Тестовый fallback", "false", "restart"),
    SettingSpec("ARACHNE_PLUGINS", "Core", "Состав встроенных плагинов", "", "build",
                "Меняется только при пересборке образа"),
    SettingSpec("DATABASE_URL", "Security", "Строка подключения к БД", "", "bootstrap", secret=True),
    SettingSpec("POSTGRES_PASSWORD", "Security", "Пароль PostgreSQL", "", "bootstrap", secret=True),
    SettingSpec("JWT_SECRET", "Security", "Ключ подписи JWT", "", "bootstrap", secret=True),
    SettingSpec("ADMIN_PASSWORD", "Security", "Пароль первого администратора", "", "bootstrap", secret=True),
    SettingSpec("ARACHNE_MASTER_KEY", "Security", "Master key шифрования", "", "bootstrap", secret=True),
    SettingSpec("ARACHNE_MASTER_KEY_SOURCE", "Security", "Источник master key", "env", "bootstrap"),
    SettingSpec("ARACHNE_MASTER_KEY_REF", "Security", "Ссылка на master key", "ARACHNE_MASTER_KEY", "bootstrap"),
    SettingSpec("VAULT_TOKEN", "Security", "Bootstrap Vault token", "", "bootstrap", secret=True),
    SettingSpec("VAULT_SECRET_ID", "Security", "Bootstrap Vault Secret ID", "", "bootstrap", secret=True),
    SettingSpec("TOKEN_TTL_DAYS", "Security", "Срок действия сессии", "7", "restart"),
)

BY_KEY = {s.key: s for s in SPECS}
LIVE_KEYS = frozenset(s.key for s in SPECS if s.mode == "live")
# Only settings consumed at process startup may be overridden here.
# Settings owned by separate admin pages, paths and bootstrap secrets stay
# read-only until their own migration/validation contracts exist.
RESTART_TYPES = {
    "FORGEJO_URL": "url", "FORGEJO_OWNER": "identifier",
    "FORGEJO_VERIFY_TLS": "bool",
    "GITLAB_URL": "url", "GITLAB_VERIFY_TLS": "bool",
    "NEXUS_URL": "url", "KOJI_PROFILE": "identifier",
    "ARACHNE_URL": "url",
    "PROXMOX_VE_ENDPOINT": "url", "PROXMOX_VE_INSECURE": "bool",
    "BUS_BACKEND": "bus", "NATS_URL": "nats_url",
}
_RESTART_BASE_ENV: dict[str, str | None] = {}
_APPLIED_RESTART_VALUES: dict[str, str] = {}


def _validated_restart(spec: SettingSpec, value: str) -> str:
    kind = RESTART_TYPES.get(spec.key)
    if kind is None or spec.mode != "restart" or spec.secret:
        raise ValueError("This setting is managed elsewhere or requires deployment configuration")
    value = str(value).strip()
    if not value or len(value) > 256 or any(ord(c) < 32 for c in value):
        raise ValueError("Value must be nonempty, at most 256 characters and contain no control characters")
    if kind in ("url", "nats_url"):
        parsed = urlsplit(value)
        schemes = ("nats", "tls", "ws", "wss") if kind == "nats_url" else ("http", "https")
        if parsed.scheme not in schemes or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Enter an absolute URL with an allowed protocol and no embedded credentials")
        if any(c.isspace() for c in value) or parsed.fragment:
            raise ValueError("URLs cannot contain spaces or fragments")
        try:
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("Invalid URL port") from exc
        return value.rstrip("/")
    if kind == "bool":
        if value.lower() not in ("true", "false"):
            raise ValueError("Expected true or false")
        return value.lower()
    if kind == "bus":
        if value.lower() not in ("inmemory", "nats"):
            raise ValueError("Expected inmemory or nats")
        return value.lower()
    if kind == "identifier":
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
            raise ValueError("Use letters, digits, dots, dashes or underscores")
        return value
    raise ValueError("Unsupported setting")


def apply_startup_overrides() -> None:
    """Call before importing application plugins, after Alembic migrations."""
    with SessionLocal() as db:
        overrides = {
            row.key: row.value for row in db.query(SettingOverride)
            .filter(SettingOverride.key.in_(list(RESTART_TYPES))).all()
        }
    for key in RESTART_TYPES:
        spec = BY_KEY[key]
        _RESTART_BASE_ENV[key] = os.environ.get(key)
        selected = overrides.get(key)
        if selected is not None:
            selected = _validated_restart(spec, selected)
            os.environ[key] = selected
        _APPLIED_RESTART_VALUES[key] = os.getenv(key, spec.default)


def restart_is_pending() -> bool:
    """True when desired restart settings differ from the boot snapshot."""
    if not _APPLIED_RESTART_VALUES:
        return False
    with SessionLocal() as db:
        overrides = {row.key: row.value for row in db.query(SettingOverride)
                     .filter(SettingOverride.key.in_(list(RESTART_TYPES))).all()}
    return any(
        overrides.get(key, _RESTART_BASE_ENV[key] if _RESTART_BASE_ENV[key] is not None else BY_KEY[key].default)
        != _APPLIED_RESTART_VALUES[key]
        for key in RESTART_TYPES
    )


def is_self_restart_available() -> bool:
    # The official Docker deployment runs a single Uvicorn worker as PID 1,
    # with restart: unless-stopped. Other deployment types need orchestration.
    return (os.getenv("ARACHNE_SELF_RESTART_ENABLED", "").lower() == "true"
            and os.getpid() == 1)


# Bound polling load: one database read per key every two seconds per process.
_VALUE_CACHE: dict[str, tuple[float, float]] = {}
_CACHE_SECONDS = 2.0


class SettingOverride(Base):
    __tablename__ = "setting_overrides"
    key = Column(String(96), primary_key=True)
    value = Column(String(256), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)
    updated_by = Column(String(128), nullable=False, default="")


class SettingChange(Base):
    __tablename__ = "setting_changes"
    id = Column(__import__("sqlalchemy").Integer, primary_key=True)
    key = Column(String(96), nullable=False)
    old_value = Column(String(256), nullable=True)
    new_value = Column(String(256), nullable=True)
    changed_at = Column(DateTime(timezone=True), nullable=False)
    actor = Column(String(128), nullable=False)


def _validated_numeric(spec: SettingSpec, value: str) -> str:
    if spec.mode != "live" or spec.secret:
        raise ValueError("This setting is not dynamically configurable")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Value must be numeric") from exc
    import math
    if not math.isfinite(number):
        raise ValueError("Value must be finite")
    if ((spec.minimum is not None and number < spec.minimum)
            or (spec.maximum is not None and number > spec.maximum)):
        raise ValueError(f"Value must be between {spec.minimum:g} and {spec.maximum:g}")
    return str(number)


def _environment_value(spec: SettingSpec) -> str:
    if spec.key in _RESTART_BASE_ENV:
        return _RESTART_BASE_ENV[spec.key] if _RESTART_BASE_ENV[spec.key] is not None else spec.default
    return os.getenv(spec.key, spec.default)


def get_numeric(key: str) -> float:
    """Live numeric lookup: DB override > environment > registered default.

    Existing running jobs may have snapshotted a deadline at dispatch time.
    """
    spec = BY_KEY.get(key)
    if spec is None or spec.mode != "live":
        raise KeyError(key)
    now = time.monotonic()
    cached = _VALUE_CACHE.get(key)
    if cached is not None and now < cached[0]:
        return cached[1]
    raw = _environment_value(spec)
    with SessionLocal() as db:
        override = db.get(SettingOverride, key)
        if override is not None:
            raw = override.value
    number = float(raw)
    _VALUE_CACHE[key] = (now + _CACHE_SECONDS, number)
    return number


def list_settings() -> list[dict]:
    with SessionLocal() as db:
        overrides = {row.key: row.value for row in db.query(SettingOverride).all()}
    result = []
    for spec in SPECS:
        present = spec.key in os.environ
        value = overrides.get(spec.key, _environment_value(spec))
        result.append({
            "key": spec.key, "label": spec.label, "group": spec.group,
            "description": spec.description, "mode": spec.mode,
            "value": None if spec.secret else value,
            "source": "override" if spec.key in overrides else "environment" if present else "default",
            "is_overridden": spec.key in overrides,
            "secret": spec.secret,
            "minimum": spec.minimum, "maximum": spec.maximum,
            "editable": spec.mode == "live" or spec.key in RESTART_TYPES,
            "input_kind": RESTART_TYPES.get(spec.key, "number"),
            "restart_pending": (spec.key in _APPLIED_RESTART_VALUES and
                value != _APPLIED_RESTART_VALUES[spec.key]),
        })
    return result


def set_override(key: str, value: str, *, actor: str) -> None:
    spec = BY_KEY.get(key)
    if spec is None:
        raise ValueError("Unknown setting")
    validated = (_validated_numeric(spec, value) if spec.mode == "live"
                 else _validated_restart(spec, value))
    now = datetime.now(timezone.utc)
    with SessionLocal.begin() as db:
        row = db.get(SettingOverride, key)
        old = row.value if row else None
        if row is None:
            row = SettingOverride(key=key, value=validated, updated_at=now, updated_by=actor)
            db.add(row)
        else:
            row.value, row.updated_at, row.updated_by = validated, now, actor
        db.add(SettingChange(key=key, old_value=old, new_value=validated,
                             changed_at=now, actor=actor))
    _VALUE_CACHE.pop(key, None)


def reset_override(key: str, *, actor: str) -> None:
    spec = BY_KEY.get(key)
    if spec is None or (spec.mode != "live" and key not in RESTART_TYPES):
        raise ValueError("Unknown or non-editable setting")
    now = datetime.now(timezone.utc)
    with SessionLocal.begin() as db:
        row = db.get(SettingOverride, key)
        if row is None:
            return
        old = row.value
        db.delete(row)
        db.add(SettingChange(key=key, old_value=old, new_value=None,
                             changed_at=now, actor=actor))
    _VALUE_CACHE.pop(key, None)
