"""Permission and scenario ACL evaluation."""
from __future__ import annotations

from sqlalchemy.orm import Session

from database import Permission, Role, RolePermission, Scenario, ScenarioACL, Team, User

SYSTEM_PERMISSIONS = {
    "scenarios.view": "View scenarios",
    "scenarios.run": "Run scenarios",
    "scenarios.create": "Create scenarios",
    "scenarios.edit": "Edit scenario drafts",
    "scenarios.publish": "Publish scenario versions",
    "scenarios.delete": "Disable scenarios",
    "scenarios.manage_acl": "Manage scenario access",
    "roles.manage": "Manage roles and teams",
    "users.manage": "Manage users",
}

SYSTEM_ROLES = {
    "admin": {"name": "Administrator", "permissions": list(SYSTEM_PERMISSIONS)},
    "developer": {
        "name": "Developer",
        "permissions": ["scenarios.view", "scenarios.run"],
    },
    "tester": {
        "name": "Tester",
        "permissions": ["scenarios.view", "scenarios.run"],
    },
}


def seed_rbac(db: Session) -> None:
    permissions: dict[str, Permission] = {}
    for slug, description in SYSTEM_PERMISSIONS.items():
        item = db.query(Permission).filter(Permission.slug == slug).first()
        if not item:
            item = Permission(slug=slug, description=description)
            db.add(item)
            db.flush()
        permissions[slug] = item
    for slug, spec in SYSTEM_ROLES.items():
        role = db.query(Role).filter(Role.slug == slug).first()
        if not role:
            role = Role(slug=slug, name=spec["name"], is_system=True)
            db.add(role)
            db.flush()
        existing = {
            row.permission_id
            for row in db.query(RolePermission).filter(RolePermission.role_id == role.id)
        }
        for permission_slug in spec["permissions"]:
            permission = permissions[permission_slug]
            if permission.id not in existing:
                db.add(RolePermission(role_id=role.id, permission_id=permission.id))
    for slug, name, components in (
        ("frontend", "Frontend", ["webapp"]),
        ("backend", "Backend", ["backend", "rpm-modern", "rpm-el7", "agent-windows"]),
        ("protocol", "Protocol", ["protocol"]),
    ):
        if not db.query(Team).filter(Team.slug == slug).first():
            db.add(Team(slug=slug, name=name, components=components))
    db.commit()


def effective_role_slugs(db: Session, user: User) -> set[str]:
    resolved: set[str] = set()
    pending = list(user.roles or [])
    while pending:
        slug = pending.pop()
        if slug in resolved:
            continue
        resolved.add(slug)
        role = db.query(Role).filter(Role.slug == slug).first()
        if role:
            pending.extend(role.inherits or [])
    return resolved


def has_permission(db: Session, user: User, permission_slug: str) -> bool:
    roles = effective_role_slugs(db, user)
    if "admin" in roles:
        return True
    return db.query(RolePermission).join(Role).join(Permission).filter(
        Role.slug.in_(roles), Permission.slug == permission_slug,
    ).first() is not None


def can_access_scenario(
    db: Session, user: User, scenario: Scenario, action: str,
) -> bool:
    roles = effective_role_slugs(db, user)
    if "admin" in roles:
        return True
    if not has_permission(db, user, f"scenarios.{action}"):
        return False
    rows = db.query(ScenarioACL).filter(
        ScenarioACL.scenario_id == scenario.id,
        ScenarioACL.permission.in_([action, "manage"]),
    ).all()
    if not rows:
        return False
    team_ids = {str(team_id) for team_id in (user.teams or [])}
    team_slugs = {
        row.slug for row in db.query(Team).filter(Team.id.in_(user.teams or [-1]))
    }
    teams = team_ids | team_slugs
    denied = any(
        row.effect == "deny"
        and (
            (row.subject_type == "role" and row.subject_key in roles)
            or (row.subject_type == "team" and row.subject_key in teams)
        )
        for row in rows
    )
    if denied:
        return False
    allowed_roles = {
        row.subject_key for row in rows
        if row.effect == "allow" and row.subject_type == "role"
    }
    allowed_teams = {
        row.subject_key for row in rows
        if row.effect == "allow" and row.subject_type == "team"
    }
    role_match = bool(roles & allowed_roles) if allowed_roles else True
    team_match = bool(teams & allowed_teams) if allowed_teams else True
    mode = next((row.match_mode for row in rows if row.effect == "allow"), "all")
    return (role_match or team_match) if mode == "any" else (role_match and team_match)
