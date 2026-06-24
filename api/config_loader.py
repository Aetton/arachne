"""Loads scenario/component config from YAML. Hot-reloadable via reload()."""
import os
import yaml

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
    with open(_resolve_path(), "r", encoding="utf-8") as f:
        _cache = yaml.safe_load(f) or {}
    return _cache


def _data():
    if not _cache:
        reload()
    return _cache


def all_scenarios() -> dict:
    return _data().get("scenarios", {})


def all_components() -> dict:
    return _data().get("components", {})


def get_scenario(key: str) -> dict | None:
    return all_scenarios().get(key)


def scenarios_for_components(components: list[str]) -> dict:
    """Filter scenarios visible to a team. '*' means all."""
    scns = all_scenarios()
    if "*" in components:
        return scns
    allowed = set(components)
    return {k: v for k, v in scns.items() if v.get("component") in allowed}
