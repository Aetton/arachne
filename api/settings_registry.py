"""Central catalog of Arachne configuration.

Only explicitly supported live numeric settings may be overridden in the DB.
Bootstrap secrets, process startup settings and build flags are inventory-only.
"""
from __future__ import annotations

import logging
import os
import time
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
    SettingSpec("NATS_URL", "Core", "NATS URL", "nats://127.0.0.1:4222", "restart"),
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
        })
    return result


def set_override(key: str, value: str, *, actor: str) -> None:
    spec = BY_KEY.get(key)
    if spec is None:
        raise ValueError("Unknown setting")
    validated = _validated_numeric(spec, value)
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
    if spec is None or spec.mode != "live":
        raise ValueError("Unknown or non-dynamic setting")
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
