"""Compatibility facade for database-backed scenarios and YAML components."""
import os
import yaml
from database import SessionLocal
import scenario_store

CONFIG_PATH = os.getenv("SCENARIOS_CONFIG", "../config/scenarios.yaml")

_cache = {}


def _resolve_path() -> str:
    # Allow running from repo root or from api/
    candidates = [
        CONFIG_PATH,
        os.path.join(os.path.dirname(__file__), "..", "config", "scenarios.yaml"),
        "config/scenarios.yaml",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    raise FileNotFoundError(f"scenarios.yaml not found; tried {candidates}")


def reload():
    global _cache
    try:
        with open(_resolve_path(), "r", encoding="utf-8") as f:
            _cache = yaml.safe_load(f) or {}
    except FileNotFoundError:
        _cache = {}
    return _cache


def _data():
    if not _cache:
        reload()
    return _cache


def all_scenarios() -> dict:
    with SessionLocal() as db:
        return scenario_store.all_published(db)


def all_components() -> dict:
    return _data().get("components", {})


def get_scenario(key: str) -> dict | None:
    with SessionLocal() as db:
        item = scenario_store.get_published(db, key)
        return dict(item[1].definition) if item else None


def scenarios_for_components(components: list[str]) -> dict:
    """Filter scenarios visible to a team. '*' means all."""
    scns = all_scenarios()
    if "*" in components:
        return scns
    allowed = set(components)
    return {k: v for k, v in scns.items() if v.get("component") in allowed}
