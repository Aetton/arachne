"""Database-backed scenario versioning, YAML bootstrap and export."""

from __future__ import annotations

from pathlib import Path
import os

import yaml
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import Component, Scenario, ScenarioACL, ScenarioVersion
from group_tree import validate_parents


_FAMILIES = {"weave", "brood", "command"}


def validate_definition(definition: dict) -> None:
    if not isinstance(definition, dict):
        raise ValueError("scenario definition must be a mapping")
    for field in ("label", "component", "steps"):
        if field not in definition:
            raise ValueError(f"missing required field: {field}")
    for field in ("label", "component"):
        if not isinstance(definition[field], str) or not definition[field].strip():
            raise ValueError(f"{field} must be a non-empty string")
    order = definition.get("sort_order", 0)
    if type(order) is not int or not -(2**31) <= order < 2**31:
        raise ValueError("sort_order must be a 32-bit integer")
    if not isinstance(definition["steps"], list) or not definition["steps"]:
        raise ValueError("steps must be a non-empty list")
    ids: set[str] = set()
    for step in definition["steps"]:
        if not isinstance(step, dict):
            raise ValueError("each step must be a mapping")
        for field in ("id", "spider", "action"):
            if not isinstance(step.get(field), str) or not step[field].strip():
                raise ValueError(f"step missing required field: {field}")
        family = step.get("family")
        if family is not None and str(family).strip().lower() not in _FAMILIES:
            raise ValueError("step family must be one of: weave, brood, command")
        if step["id"] in ids:
            raise ValueError(f"duplicate step id: {step['id']}")
        ids.add(step["id"])


def published_definition(db: Session, scenario: Scenario) -> dict | None:
    if not scenario.current_version_id:
        return None
    version = db.get(ScenarioVersion, scenario.current_version_id)
    if not version:
        return None
    definition = dict(version.definition)
    definition["sort_order"] = scenario.sort_order
    return definition


def editable_definition(db: Session, scenario: Scenario) -> dict | None:
    if scenario.current_version_id:
        return published_definition(db, scenario)
    version = (
        db.query(ScenarioVersion)
        .filter(ScenarioVersion.scenario_id == scenario.id)
        .order_by(ScenarioVersion.version.desc())
        .first()
    )
    if not version:
        return None
    return {**version.definition, "sort_order": scenario.sort_order}


def get_published(db: Session, slug: str) -> tuple[Scenario, ScenarioVersion] | None:
    scenario = (
        db.query(Scenario)
        .filter(
            Scenario.slug == slug,
            Scenario.enabled.is_(True),
        )
        .first()
    )
    if not scenario or not scenario.current_version_id:
        return None
    version = db.get(ScenarioVersion, scenario.current_version_id)
    return (scenario, version) if version else None


def all_published(db: Session) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for scenario in db.query(Scenario).filter(Scenario.enabled.is_(True)).all():
        definition = published_definition(db, scenario)
        if definition:
            result[scenario.slug] = definition
    return result


def save_draft(
    db: Session,
    slug: str,
    definition: dict,
    user_id: int | None,
    comment: str = "",
    *,
    commit: bool = True,
) -> ScenarioVersion:
    validate_definition(definition)
    component_slug = str(definition["component"]).strip()
    if not db.get(Component, component_slug):
        raise ValueError(f"unknown component: {component_slug}")
    definition = dict(definition)
    definition["component"] = component_slug
    scenario = db.query(Scenario).filter(Scenario.slug == slug).first()
    if not scenario:
        scenario = Scenario(
            slug=slug,
            label=definition["label"],
            component=definition["component"],
            created_by=user_id,
        )
        db.add(scenario)
        db.flush()
    if "sort_order" in definition:
        scenario.sort_order = int(definition["sort_order"])
    scenario.label = definition["label"]
    scenario.component = definition["component"]
    next_version = (
        db.query(func.max(ScenarioVersion.version))
        .filter(ScenarioVersion.scenario_id == scenario.id)
        .scalar()
        or 0
    ) + 1
    version = ScenarioVersion(
        scenario_id=scenario.id,
        version=next_version,
        definition=definition,
        status="draft",
        created_by=user_id,
        comment=comment,
    )
    db.add(version)
    db.commit() if commit else db.flush()
    db.refresh(version)
    return version


def publish(
    db: Session, scenario: Scenario, version: ScenarioVersion, *, commit: bool = True
) -> None:
    if version.scenario_id != scenario.id:
        raise ValueError("version does not belong to scenario")
    validate_definition(version.definition)
    if scenario.current_version_id:
        current = db.get(ScenarioVersion, scenario.current_version_id)
        if current and current.id != version.id:
            current.status = "archived"
    version.status = "published"
    scenario.current_version_id = version.id
    scenario.enabled = True
    db.commit() if commit else db.flush()


def export_yaml(db: Session) -> str:
    scenarios = all_published(db)
    for scenario in db.query(Scenario).all():
        if scenario.slug not in scenarios:
            continue
        scenarios[scenario.slug]["sort_order"] = scenario.sort_order
        rows = (
            db.query(ScenarioACL).filter(ScenarioACL.scenario_id == scenario.id).all()
        )
        if not rows:
            continue
        access: dict = {}
        for row in rows:
            rule = access.setdefault(
                row.permission,
                {
                    "match": row.match_mode,
                    "roles": [],
                    "teams": [],
                },
            )
            rule["roles" if row.subject_type == "role" else "teams"].append(
                row.subject_key
            )
        scenarios[scenario.slug]["access"] = access
    return yaml.safe_dump(
        {
            "components": {
                component.slug: {
                    "label": component.label,
                    "icon": component.icon,
                    "sort_order": component.sort_order,
                    "parent_group": component.parent_group,
                }
                for component in db.query(Component).order_by(
                    Component.sort_order,
                    Component.label,
                )
            },
            "scenarios": scenarios,
        },
        allow_unicode=True,
        sort_keys=False,
    )


def bootstrap_from_yaml(db: Session) -> int:
    """Seed absent components and scenarios. Never overwrite database edits."""
    raw_path = os.getenv("SCENARIOS_CONFIG", "/app/config/scenarios.yaml")
    candidates = [
        Path(raw_path),
        Path(__file__).parent.parent / "config" / "scenarios.yaml",
        Path(__file__).parent.parent / "config" / "scenarios.yaml.example",
    ]
    path = next((candidate for candidate in candidates if candidate.exists()), None)
    if not path:
        return 0
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    imported_groups = []
    for index, (slug, spec) in enumerate((payload.get("components") or {}).items()):
        component = db.get(Component, slug)
        if component:
            fallback_label = slug.replace("-", " ").title()
            if component.label == fallback_label and component.icon == "ti-box":
                component.label = spec.get("label") or component.label
                component.icon = spec.get("icon") or component.icon
                component.sort_order = int(spec.get("sort_order", index))
            continue
        spec = spec or {}
        imported_groups.append((slug, spec.get("parent_group") or None))
        db.add(
            Component(
                slug=slug,
                label=spec.get("label") or slug,
                icon=spec.get("icon") or "ti-box",
                sort_order=int(spec.get("sort_order", index)),
            )
        )
    db.flush()
    parents = {c.slug: c.parent_group for c in db.query(Component).all()}
    parents.update(dict(imported_groups))
    validate_parents(parents)
    for slug, parent in imported_groups:
        db.get(Component, slug).parent_group = parent
    db.commit()

    imported = 0
    for slug, definition in (payload.get("scenarios") or {}).items():
        if db.query(Scenario).filter(Scenario.slug == slug).first():
            continue
        definition = dict(definition)
        access = definition.pop("access", {})
        version = save_draft(db, slug, definition, None, "Imported from YAML bootstrap")
        scenario = db.query(Scenario).filter(Scenario.slug == slug).one()
        publish(db, scenario, version)
        entries = []
        for permission, rule in access.items():
            mode = rule.get("match", "all")
            for role in rule.get("roles", []):
                entries.append(
                    {
                        "subject_type": "role",
                        "subject_key": str(role),
                        "permission": permission,
                        "effect": "allow",
                        "match_mode": mode,
                    }
                )
            for team in rule.get("teams", []):
                entries.append(
                    {
                        "subject_type": "team",
                        "subject_key": str(team),
                        "permission": permission,
                        "effect": "allow",
                        "match_mode": mode,
                    }
                )
        if entries:
            replace_acl(db, scenario.id, entries)
        imported += 1
    return imported


def replace_acl(
    db: Session, scenario_id: int, entries: list[dict], *, commit: bool = True
) -> None:
    db.query(ScenarioACL).filter(ScenarioACL.scenario_id == scenario_id).delete()
    for entry in entries:
        db.add(ScenarioACL(scenario_id=scenario_id, **entry))
    db.commit() if commit else db.flush()


def move_to_group(db: Session, slug: str, target: str, user_id: int) -> None:
    """Move without changing ACL, enabled status or historical definitions."""
    # Serialize group changes with layout operations and validate destination.
    groups = {c.slug for c in db.query(Component).with_for_update().all()}
    if target not in groups:
        raise ValueError("Unknown destination group")
    scenario = (
        db.query(Scenario).filter(Scenario.slug == slug).with_for_update().first()
    )
    if not scenario:
        raise ValueError("Unknown scenario")
    if scenario.component == target:
        return
    source = (
        db.get(ScenarioVersion, scenario.current_version_id)
        if scenario.current_version_id
        else (
            db.query(ScenarioVersion)
            .filter(ScenarioVersion.scenario_id == scenario.id)
            .order_by(ScenarioVersion.version.desc())
            .first()
        )
    )
    if not source:
        raise ValueError("Scenario has no definition to move")
    order = (
        db.query(func.max(Scenario.sort_order))
        .filter(Scenario.component == target)
        .scalar()
    )
    order = (order if order is not None else -1) + 1
    definition = dict(source.definition)
    definition.update(component=target, sort_order=order)
    validate_definition(definition)
    next_version = (
        db.query(func.max(ScenarioVersion.version))
        .filter(ScenarioVersion.scenario_id == scenario.id)
        .scalar()
        or 0
    ) + 1
    published = bool(scenario.current_version_id)
    version = ScenarioVersion(
        scenario_id=scenario.id,
        version=next_version,
        definition=definition,
        status="published" if published else "draft",
        created_by=user_id,
        comment=f"Moved from {scenario.component} to {target}",
    )
    db.add(version)
    db.flush()
    if published:
        source.status = "archived"
        scenario.current_version_id = version.id
    scenario.component = target
    scenario.sort_order = order
    db.commit()
