"""Validate and import a complete scenario bundle in one transaction."""

import json
import re
import yaml
from database import Component, Scenario
from group_tree import validate_parents
import scenario_store

MAX_BYTES = 5 * 1024 * 1024
PERMISSIONS = {"view", "run", "edit", "manage"}


class BundleLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise ValueError("YAML mapping keys must be strings")
        if key in result:
            raise ValueError(f"Duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


BundleLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping
)


def mapping(value, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    return value


def acl_entries(definition):
    """Accept legacy allow rules or lossless exported ACL rows."""
    if "access_rules" in definition and "access" in definition:
        raise ValueError("Use access or access_rules, not both")
    if "access_rules" in definition:
        rows = definition["access_rules"]
        if not isinstance(rows, list):
            raise ValueError("access_rules must be a list")
        result = []
        for row in rows:
            mapping(row, "ACL rule")
            if set(row) != {
                "subject_type",
                "subject_key",
                "permission",
                "effect",
                "match_mode",
            }:
                raise ValueError("Invalid ACL rule fields")
            result.append(dict(row))
    else:
        result = []
        for permission, rule in mapping(definition.get("access", {}), "access").items():
            mapping(rule, "access rule")
            if set(rule) - {"match", "roles", "teams"}:
                raise ValueError("Unknown access rule fields")
            for field, kind in (("roles", "role"), ("teams", "team")):
                subjects = rule.get(field, [])
                if not isinstance(subjects, list):
                    raise ValueError(f"access.{permission}.{field} must be a list")
                for subject in subjects:
                    if not isinstance(subject, (str, int)) or isinstance(subject, bool):
                        raise ValueError("ACL subject must be a string or integer")
                    result.append(
                        dict(
                            subject_type=kind,
                            subject_key=str(subject),
                            permission=permission,
                            effect="allow",
                            match_mode=rule.get("match", "all"),
                        )
                    )
            if permission not in PERMISSIONS or rule.get("match", "all") not in {
                "all",
                "any",
            }:
                raise ValueError("Invalid ACL permission or match mode")
    for row in result:
        if (
            row["subject_type"] not in ("role", "team")
            or row["permission"] not in PERMISSIONS
            or row["effect"] not in ("allow", "deny")
            or row["match_mode"] not in ("all", "any")
            or not isinstance(row["subject_key"], str)
            or not row["subject_key"].strip()
        ):
            raise ValueError("Invalid ACL rule")
    return result


def import_bundle(db, text, mode, user):
    if mode not in {"add", "update"}:
        raise ValueError("Import mode must be add or update")
    payload = mapping(yaml.load(text, Loader=BundleLoader), "YAML root")
    if set(payload) - {"components", "scenarios"}:
        raise ValueError("Unknown bundle fields")
    # Reject YAML-specific values and recursive aliases before SQL JSON serialization.
    json.dumps(payload, allow_nan=False)
    components = mapping(payload.get("components", {}), "components")
    scenarios = mapping(payload.get("scenarios", {}), "scenarios")
    if not components and not scenarios:
        raise ValueError("Bundle contains no components or scenarios")
    groups = {c.slug: c for c in db.query(Component).with_for_update().all()}
    parents = {slug: c.parent_group for slug, c in groups.items()}
    result = {
        key: 0
        for key in (
            "componentsCreated",
            "componentsUpdated",
            "componentsSkipped",
            "scenariosCreated",
            "scenariosUpdated",
            "scenariosSkipped",
        )
    }
    changed = []
    for index, (slug, spec) in enumerate(components.items()):
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,95}", slug):
            raise ValueError(f"Invalid group slug: {slug}")
        if slug in groups and mode == "add":
            result["componentsSkipped"] += 1
            continue
        spec = mapping(spec, slug)
        parent = spec.get("parent_group")
        if parent is not None and not isinstance(parent, str):
            raise ValueError(f"{slug}: parent_group must be a string or null")
        parents[slug] = parent or None
        label, icon, order = (
            spec.get("label", slug),
            spec.get("icon", "ti-box"),
            spec.get("sort_order", index),
        )
        if not isinstance(label, str) or not label.strip() or len(label) > 160:
            raise ValueError(f"{slug}: invalid label")
        if not isinstance(icon, str) or len(icon) > 64:
            raise ValueError(f"{slug}: invalid icon")
        if type(order) is not int or not -(2**31) <= order < 2**31:
            raise ValueError(f"{slug}: sort_order must be a 32-bit integer")
        exists = slug in groups
        row = groups.get(slug) or Component(slug=slug)
        row.label, row.icon, row.sort_order = label.strip(), icon, order
        db.add(row)
        groups[slug] = row
        changed.append(slug)
        result["componentsUpdated" if exists else "componentsCreated"] += 1
    validate_parents(parents)
    db.flush()  # All new groups exist before assigning forward parent references.
    for slug in changed:
        groups[slug].parent_group = parents[slug]
    db.flush()
    for slug, raw in scenarios.items():
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", slug):
            raise ValueError(f"Invalid scenario slug: {slug}")
        scenario = (
            db.query(Scenario).filter(Scenario.slug == slug).with_for_update().first()
        )
        if scenario and mode == "add":
            result["scenariosSkipped"] += 1
            continue
        definition = dict(mapping(raw, slug))
        explicit_acl = "access" in definition or "access_rules" in definition
        entries = acl_entries(definition)
        definition.pop("access", None)
        definition.pop("access_rules", None)
        is_new = scenario is None
        if is_new and not explicit_acl:
            entries = [
                dict(
                    subject_type=kind,
                    subject_key=str(subject),
                    permission=permission,
                    effect="allow",
                    match_mode="all",
                )
                for permission in PERMISSIONS
                for kind, subjects in (
                    ("role", user.roles or []),
                    ("team", user.teams or []),
                )
                for subject in subjects
            ]
        version = scenario_store.save_draft(
            db, slug, definition, user.id, "Imported from YAML", commit=False
        )
        scenario = db.query(Scenario).filter(Scenario.slug == slug).one()
        scenario_store.publish(db, scenario, version, commit=False)
        if explicit_acl or is_new:
            scenario_store.replace_acl(db, scenario.id, entries, commit=False)
        result["scenariosCreated" if is_new else "scenariosUpdated"] += 1
    db.commit()
    return result
