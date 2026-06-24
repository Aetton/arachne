"""Minimal plugin system. A plugin can mutate params before a run and/or
validate them. Teams enable plugins by name in their config later.

This is intentionally tiny — the seam exists so frontend/backend teams can
add component-specific behaviour (custom env vars, swagger toggles) without
touching core code.
"""
from abc import ABC


class BasePlugin(ABC):
    name: str = "base"

    def transform_params(self, scenario_key: str, params: dict) -> dict:
        return params

    def validate(self, scenario_key: str, params: dict) -> list[str]:
        """Return a list of error strings; empty = OK."""
        return []


REGISTRY: dict[str, BasePlugin] = {}


def register(plugin: BasePlugin):
    REGISTRY[plugin.name] = plugin
    return plugin


def apply_transforms(scenario_key: str, params: dict, enabled: list[str]) -> dict:
    for name in enabled:
        p = REGISTRY.get(name)
        if p:
            params = p.transform_params(scenario_key, params)
    return params
