"""Compatibility facade for database-backed scenario configuration."""
from database import Component, SessionLocal
import scenario_store


def all_scenarios() -> dict:
    with SessionLocal() as db:
        return scenario_store.all_published(db)


def all_components() -> dict:
    with SessionLocal() as db:
        return {
            component.slug: {
                "label": component.label,
                "icon": component.icon,
                "sort_order": component.sort_order,
            }
            for component in db.query(Component).order_by(
                Component.sort_order, Component.label,
            )
        }


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
