"""Transactional scenario/group layout operations, independent of HTTP."""

from database import Component, Scenario
from group_tree import validate_parents
import scenario_store


def apply_layout(db, payload, user_id):
    kind, slug, before = payload.get("kind"), payload.get("slug"), payload.get("before")
    if kind == "move_scenario":
        scenario_store.move_to_group(db, slug, payload.get("group"), user_id)
        return {"ok": True}
    if kind == "group":
        rows = (
            db.query(Component)
            .order_by(Component.sort_order, Component.label, Component.slug)
            .with_for_update()
            .all()
        )
        mapping = {r.slug: r for r in rows}
        if slug not in mapping:
            raise ValueError("Unknown group")
        parent = payload.get("parent_group") or None
        parents = {r.slug: r.parent_group for r in rows}
        parents[slug] = parent
        validate_parents(parents)
        siblings = [r for r in rows if r.parent_group == parent and r.slug != slug]
        if before and before not in {r.slug for r in siblings}:
            raise ValueError("Invalid target group")
        row = mapping[slug]
        row.parent_group = parent
    elif kind == "scenario":
        row = db.query(Scenario).filter(Scenario.slug == slug).first()
        if not row:
            raise ValueError("Unknown scenario")
        siblings = (
            db.query(Scenario)
            .filter(Scenario.component == row.component)
            .order_by(Scenario.sort_order, Scenario.label, Scenario.slug)
            .with_for_update()
            .all()
        )
        siblings = [r for r in siblings if r.slug != slug]
        if before and before not in {r.slug for r in siblings}:
            raise ValueError("Scenarios can only be reordered within their group")
    else:
        raise ValueError("Unknown layout operation")
    index = next((i for i, r in enumerate(siblings) if r.slug == before), len(siblings))
    siblings.insert(index, row)
    for index, item in enumerate(siblings):
        item.sort_order = index
    db.commit()
