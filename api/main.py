"""Arachne — FastAPI entrypoint.

Run: uvicorn main:app --reload  (from api/ dir)
Seeds an 'admin/admin' user on first boot (change immediately).
"""
import os
import json
import re
from datetime import datetime, timezone

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

import database
from database import (
    SessionLocal, User, Team, Role, Permission, RolePermission, Run, Component, Scenario,
    ScenarioACL, ScenarioVersion, utcnow,
)
from auth.security import hash_password, verify_password, create_token
from auth.deps import (
    get_db, get_current_user, get_optional_user, require_role, COOKIE_NAME,
)
import config_loader
import scenario_store
import access
import run_engine
import runview
from core import switchboard
from pydantic import BaseModel

BASE_DIR = os.path.dirname(__file__)
TEMPLATES_DIR = os.path.join(BASE_DIR, "..", "frontend", "templates")
STATIC_DIR = os.path.join(BASE_DIR, "..", "frontend", "static")

templates = Jinja2Templates(directory=TEMPLATES_DIR)


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    db = SessionLocal()
    access.seed_rbac(db)
    scenario_store.bootstrap_from_yaml(db)
    db.close()
    from core.bus import start_bus
    from core import events as _events
    await start_bus()                       # bring the bus up first
    run_engine.init()                       # load plugins + wire triggers
    await _events.wire()                    # flush queued subscriptions onto the bus
    from core.thread_adapter import expose_all
    await expose_all()                       # put local drivers onto the bus as responders
    try:
        from plugins.triggers.schedule import start_scheduler
        start_scheduler()
    except Exception as exc:  # noqa: BLE001
        print(f"[lifespan] scheduler not started: {exc}")
    db = SessionLocal()
    if not db.query(User).filter(User.username == "admin").first():
        db.add(User(
            username="admin",
            password_hash=hash_password(os.getenv("ADMIN_PASSWORD", "admin")),
            full_name="Administrator",
            roles=["admin"], teams=[], is_active=True,
        ))
        db.commit()
    db.close()
    yield
    from core.bus import stop_bus
    await stop_bus()


app = FastAPI(title="Arachne", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


# ---------- thread callbacks (runners report back here) ----------
# Law of the thread: a signal is accepted only if its token matches the one the
# spider stamped at dispatch. No auth cookie — runners are external; the token
# IS the auth.

class BlockSignal(BaseModel):
    step: str
    status: str = "ok"           # ok | failed
    output: str = ""


class FinalSignal(BaseModel):
    status: str                  # success | failed | cancelled
    artifacts: list[dict] = []


def _thread_token(request: Request) -> str:
    # accept token via header (preferred) or ?token= for curl simplicity
    return (request.headers.get("X-Arachne-Token")
            or request.query_params.get("token", ""))


@app.post("/api/threads/{build_id}/signal")
async def thread_signal(build_id: str, block: BlockSignal, request: Request):
    token = _thread_token(request)
    ok = switchboard.signal_block(build_id, token, block.model_dump())
    if not ok:
        raise HTTPException(status_code=403, detail="thread token mismatch")
    return {"accepted": True}


@app.post("/api/threads/{build_id}/status")
async def thread_status(build_id: str, final: FinalSignal, request: Request):
    token = _thread_token(request)
    ok = switchboard.signal_final(build_id, token, final.status, final.artifacts)
    if not ok:
        raise HTTPException(status_code=403, detail="thread token mismatch")
    return {"accepted": True}


# ---------- helpers ----------
def render(request, name, **ctx):
    return templates.TemplateResponse(request, name, ctx)


def _fmt_when(dt) -> str:
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    s = int(delta.total_seconds())
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return dt.strftime("%Y-%m-%d %H:%M")


# ---------- auth ----------
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, user=Depends(get_optional_user)):
    if user:
        return RedirectResponse("/", status_code=302)
    return render(request, "login.html", user=None)


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...),
          db: Session = Depends(get_db)):
    u = db.query(User).filter(User.username == username).first()
    if not u or not u.is_active or not verify_password(password, u.password_hash):
        return render(request, "login.html", user=None, error="Invalid credentials")
    u.last_login = utcnow()
    db.commit()
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(COOKIE_NAME, create_token(u.username), httponly=True,
                    samesite="lax", max_age=7 * 86400)
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(COOKIE_NAME)
    return resp


# ---------- dashboard ----------
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, user=Depends(get_optional_user), db: Session = Depends(get_db)):
    if not user:
        return RedirectResponse("/login", status_code=302)
    groups = []
    components = db.query(Component).order_by(
        Component.sort_order, Component.label,
    ).all()
    for component in components:
        items = []
        scenarios = db.query(Scenario).filter(
            Scenario.enabled.is_(True),
            Scenario.component == component.slug,
        ).order_by(Scenario.label).all()
        for scenario in scenarios:
            definition = scenario_store.published_definition(db, scenario)
            if definition and access.can_access_scenario(db, user, scenario, "view"):
                items.append({"slug": scenario.slug, "definition": definition})
        if items:
            groups.append({"component": component, "scenarios": items})
    return render(request, "dashboard.html", user=user, scenario_groups=groups)


# ---------- scenarios ----------
@app.get("/scenarios/{key}/form", response_class=HTMLResponse)
def scenario_form(key: str, request: Request, user=Depends(get_current_user),
                  db: Session = Depends(get_db)):
    stored = db.query(Scenario).filter(Scenario.slug == key).first()
    if not stored or not access.can_access_scenario(db, user, stored, "view"):
        raise HTTPException(404, "Unknown scenario")
    s = config_loader.get_scenario(key)
    if not s:
        raise HTTPException(404, "Unknown scenario")
    return render(request, "scenario_form.html", user=user, key=key, s=s)


@app.post("/scenarios/{key}/run", response_class=HTMLResponse)
async def scenario_run(key: str, request: Request, user=Depends(get_current_user),
                       db: Session = Depends(get_db)):
    stored = db.query(Scenario).filter(Scenario.slug == key).first()
    if not stored or not access.can_access_scenario(db, user, stored, "run"):
        raise HTTPException(403, "Scenario run is not allowed")
    s = config_loader.get_scenario(key)
    if not s:
        raise HTTPException(404, "Unknown scenario")

    form = await request.form()
    params = {}
    for p in s.get("params", []):
        name = p["name"]
        if p["type"] == "boolean":
            params[name] = name in form
        else:
            params[name] = form.get(name, p.get("default", ""))

    run_id = await run_engine.start_run_async(user.id, key, params)

    resp = _render_run(request, user, run_id)
    resp.headers["HX-Trigger"] = "runStarted"
    return resp


# ---------- runs ----------
def _render_run(request, user, run_id) -> HTMLResponse:
    db = SessionLocal()
    run = db.get(Run, run_id)
    s = config_loader.get_scenario(run.scenario) or {"label": run.scenario}

    if run.status == "running":
        records = run_engine.live_records(run_id)
    else:
        try:
            records = json.loads(run.log or "[]")
        except (ValueError, TypeError):
            records = []

    steps = runview.build(records, run.status)

    arts = [
        {"name": a.get("name", "artifact"),
         "url": a.get("download_url") or "#",
         "repo": a.get("type", "")}
        for a in (run.artifacts or [])
        if a.get("download_url")
    ]
    db.close()
    return render(request, "run_view.html",
                  user=user, run=run, s=s, steps=steps, artifacts=arts)


@app.get("/runs/{run_id}/view", response_class=HTMLResponse)
def run_view(run_id: str, request: Request, user=Depends(get_current_user)):
    return _render_run(request, user, run_id)


@app.post("/runs/{run_id}/cancel")
async def run_cancel(run_id: str, request: Request, user=Depends(get_current_user)):
    """Signal cancel for the run's currently active step(s). Best-effort: the
    spider cuts its own thread. Full per-step targeting is a later refinement."""
    db = SessionLocal()
    run = db.get(Run, run_id)
    scenario = config_loader.get_scenario(run.scenario) if run else None
    db.close()
    if not scenario:
        raise HTTPException(404)
    from core.thread_client import cancel_step
    from core import orchestrator
    for step in orchestrator.parse_steps(scenario):
        await cancel_step(run_id, step.kind, step.spider, step.id)
    return Response("", headers={"HX-Trigger": "runStarted"})


@app.get("/runs/history", response_class=HTMLResponse)
def runs_history(request: Request, user=Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(Run)
    if "admin" not in (user.roles or []):
        q = q.filter(Run.user_id == user.id)
    runs = q.order_by(Run.created_at.desc()).limit(15).all()
    rows = []
    for r in runs:
        s = config_loader.get_scenario(r.scenario) or {}
        rows.append({
            "id": r.id, "status": r.status, "params": r.params or {},
            "scenario_label": s.get("label", r.scenario),
            "when": _fmt_when(r.created_at),
        })
    return render(request, "runs_history.html", user=user, runs=rows)


@app.get("/runs/{run_id}/stream")
async def run_stream(run_id: str, user=Depends(get_current_user)):
    """SSE raw log tail — for clients that want token-level streaming."""
    async def gen():
        import asyncio
        sent = 0
        while True:
            lines = run_engine.live_lines(run_id)
            while sent < len(lines):
                yield f"data: {lines[sent]}\n\n"
                sent += 1
            if run_engine.is_done(run_id):
                yield "event: done\ndata: end\n\n"
                return
            await asyncio.sleep(0.4)
    return StreamingResponse(gen(), media_type="text/event-stream")


# ---------- admin ----------
@app.get("/admin/users", response_class=HTMLResponse)
def admin_users(request: Request, user=Depends(require_role("admin")), db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.username).all()
    return render(request, "admin/users.html", user=user, users=users, current_user=user)


@app.get("/admin/users/new", response_class=HTMLResponse)
def admin_user_new(request: Request, user=Depends(require_role("admin")), db: Session = Depends(get_db)):
    teams = db.query(Team).all()
    roles = db.query(Role).order_by(Role.slug).all()
    return render(request, "admin/user_form.html", user=user, edit=False, u=None,
                  all_roles=roles, all_teams=teams, action="/admin/users")


@app.get("/admin/users/{uid}/edit", response_class=HTMLResponse)
def admin_user_edit(uid: int, request: Request, user=Depends(require_role("admin")),
                    db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404)
    teams = db.query(Team).all()
    roles = db.query(Role).order_by(Role.slug).all()
    return render(request, "admin/user_form.html", user=user, edit=True, u=u,
                  all_roles=roles, all_teams=teams, action=f"/admin/users/{uid}")


@app.post("/admin/users")
async def admin_user_create(request: Request, user=Depends(require_role("admin")),
                            db: Session = Depends(get_db)):
    form = await request.form()
    if db.query(User).filter(User.username == form["username"]).first():
        raise HTTPException(400, "User exists")
    db.add(User(
        username=form["username"],
        password_hash=hash_password(form.get("password") or "changeme"),
        full_name=form.get("full_name", ""),
        roles=form.getlist("roles"),
        teams=[int(x) for x in form.getlist("teams")],
        is_active="is_active" in form,
    ))
    db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@app.post("/admin/users/{uid}")
async def admin_user_update(uid: int, request: Request, user=Depends(require_role("admin")),
                            db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404)
    form = await request.form()
    u.full_name = form.get("full_name", "")
    u.roles = form.getlist("roles")
    u.teams = [int(x) for x in form.getlist("teams")]
    u.is_active = "is_active" in form
    if form.get("password"):
        u.password_hash = hash_password(form["password"])
    db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@app.delete("/admin/users/{uid}")
def admin_user_delete(uid: int, user=Depends(require_role("admin")), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if u and u.username != user.username:
        db.delete(u)
        db.commit()
    return Response("")


# ---------- scenario administration ----------
@app.get("/admin/scenarios", response_class=HTMLResponse)
def admin_scenarios(request: Request, user=Depends(require_role("admin")),
                    db: Session = Depends(get_db)):
    scenarios = db.query(Scenario).order_by(Scenario.slug).all()
    components = db.query(Component).order_by(
        Component.sort_order, Component.label,
    ).all()
    return render(
        request, "admin/scenarios.html", user=user,
        scenarios=scenarios, components=components,
    )


@app.get("/admin/scenarios/new", response_class=HTMLResponse)
def admin_scenario_new(request: Request, user=Depends(require_role("admin")),
                       db: Session = Depends(get_db)):
    roles = db.query(Role).order_by(Role.slug).all()
    teams = db.query(Team).order_by(Team.name).all()
    components = db.query(Component).order_by(
        Component.sort_order, Component.label,
    ).all()
    default_component = components[0].slug if components else ""
    return render(
        request, "admin/scenario_form.html", user=user, scenario=None,
        yaml_text=f"label: New scenario\ncomponent: {default_component}\ntriggers:\n  - type: manual\nsteps:\n  - id: build\n    spider: forgejo\n    action: build\n    with: {{}}\n",
        roles=roles, teams=teams, components=components, acl=[],
        default_acl_roles=set(user.roles or []),
        default_acl_teams={int(team_id) for team_id in (user.teams or [])},
    )


@app.get("/admin/scenarios/{slug}/edit", response_class=HTMLResponse)
def admin_scenario_edit(slug: str, request: Request, user=Depends(require_role("admin")),
                        db: Session = Depends(get_db)):
    import yaml
    scenario = db.query(Scenario).filter(Scenario.slug == slug).first()
    if not scenario:
        raise HTTPException(404)
    definition = scenario_store.published_definition(db, scenario) or {}
    return render(
        request, "admin/scenario_form.html", user=user, scenario=scenario,
        yaml_text=yaml.safe_dump(definition, allow_unicode=True, sort_keys=False),
        roles=db.query(Role).order_by(Role.slug).all(),
        teams=db.query(Team).order_by(Team.name).all(),
        components=db.query(Component).order_by(
            Component.sort_order, Component.label,
        ).all(),
        acl=db.query(ScenarioACL).filter(ScenarioACL.scenario_id == scenario.id).all(),
        versions=db.query(ScenarioVersion).filter(
            ScenarioVersion.scenario_id == scenario.id,
        ).order_by(ScenarioVersion.version.desc()).all(),
    )


@app.post("/admin/scenarios/save")
async def admin_scenario_save(request: Request, user=Depends(require_role("admin")),
                              db: Session = Depends(get_db)):
    import yaml
    form = await request.form()
    slug = str(form.get("slug", "")).strip()
    original_slug = str(form.get("original_slug", "")).strip()
    if not slug:
        raise HTTPException(400, "Scenario slug is required")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", slug):
        raise HTTPException(
            400,
            "Scenario slug must start with a lowercase letter or digit and contain "
            "only lowercase letters, digits, dots, underscores, and hyphens "
            "(64 characters maximum)",
        )
    try:
        scenario = None
        is_new = not original_slug
        if original_slug:
            scenario = db.query(Scenario).filter(Scenario.slug == original_slug).first()
            if not scenario:
                raise HTTPException(404, "Scenario not found")
            conflict = db.query(Scenario).filter(
                Scenario.slug == slug,
                Scenario.id != scenario.id,
            ).first()
            if conflict:
                raise HTTPException(409, f"Scenario slug '{slug}' already exists")
        elif db.query(Scenario).filter(Scenario.slug == slug).first():
            raise HTTPException(409, f"Scenario slug '{slug}' already exists")

        definition = yaml.safe_load(form.get("definition", "")) or {}
        if scenario and slug != original_slug:
            scenario.slug = slug
            db.query(Run).filter(Run.scenario == original_slug).update(
                {Run.scenario: slug},
                synchronize_session=False,
            )
            db.flush()
        version = scenario_store.save_draft(
            db, slug, definition, user.id, str(form.get("comment", "")),
        )
        scenario = db.query(Scenario).filter(Scenario.slug == slug).one()
        scenario_store.publish(db, scenario, version)
        entries = []
        mode = str(form.get("match_mode", "all"))
        submitted_subjects = any(
            form.getlist(f"{action}_{subject_type}")
            for action in ("view", "run", "edit", "manage")
            for subject_type in ("roles", "teams")
        )
        for action in ("view", "run", "edit", "manage"):
            role_slugs = form.getlist(f"{action}_roles")
            team_ids = form.getlist(f"{action}_teams")
            if is_new and not submitted_subjects:
                role_slugs = [str(role) for role in (user.roles or [])]
                team_ids = [str(team_id) for team_id in (user.teams or [])]
            for role_slug in role_slugs:
                entries.append({
                    "subject_type": "role", "subject_key": role_slug,
                    "permission": action, "effect": "allow", "match_mode": mode,
                })
            for team_id in team_ids:
                entries.append({
                    "subject_type": "team", "subject_key": team_id,
                    "permission": action, "effect": "allow", "match_mode": mode,
                })
        scenario_store.replace_acl(db, scenario.id, entries)
    except (ValueError, yaml.YAMLError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/admin/scenarios", status_code=303)


@app.post("/admin/components")
async def admin_component_save(request: Request, user=Depends(require_role("admin")),
                               db: Session = Depends(get_db)):
    form = await request.form()
    slug = str(form.get("slug", "")).strip()
    if not slug:
        raise HTTPException(400, "Component slug is required")
    component = db.get(Component, slug)
    if not component:
        component = Component(slug=slug, label=slug)
        db.add(component)
    component.label = str(form.get("label") or slug).strip()
    component.icon = str(form.get("icon") or "ti-box").strip()
    try:
        component.sort_order = int(form.get("sort_order") or 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "Component order must be an integer") from exc
    db.commit()
    return RedirectResponse("/admin/scenarios", status_code=303)


@app.post("/admin/components/{slug}/delete")
def admin_component_delete(slug: str, user=Depends(require_role("admin")),
                           db: Session = Depends(get_db)):
    component = db.get(Component, slug)
    if not component:
        raise HTTPException(404, "Component not found")
    scenario_count = db.query(Scenario).filter(Scenario.component == slug).count()
    if scenario_count:
        raise HTTPException(
            409,
            f"Component '{slug}' is used by {scenario_count} scenario(s)",
        )
    db.delete(component)
    db.commit()
    return RedirectResponse("/admin/scenarios", status_code=303)


@app.post("/admin/scenarios/{slug}/versions/{version_id}/restore")
def admin_scenario_restore(slug: str, version_id: int,
                           user=Depends(require_role("admin")),
                           db: Session = Depends(get_db)):
    scenario = db.query(Scenario).filter(Scenario.slug == slug).first()
    version = db.get(ScenarioVersion, version_id)
    if not scenario or not version or version.scenario_id != scenario.id:
        raise HTTPException(404)
    restored = scenario_store.save_draft(
        db, slug, dict(version.definition), user.id,
        f"Restored from version {version.version}",
    )
    scenario_store.publish(db, scenario, restored)
    return RedirectResponse(f"/admin/scenarios/{slug}/edit", status_code=303)


@app.get("/admin/scenarios-export.yaml")
def admin_scenarios_export(user=Depends(require_role("admin")),
                           db: Session = Depends(get_db)):
    return Response(
        scenario_store.export_yaml(db),
        media_type="application/yaml",
        headers={"Content-Disposition": "attachment; filename=scenarios.yaml"},
    )


# ---------- RBAC administration ----------
@app.get("/admin/rbac", response_class=HTMLResponse)
def admin_rbac(request: Request, user=Depends(require_role("admin")),
               db: Session = Depends(get_db)):
    roles = db.query(Role).order_by(Role.slug).all()
    teams = db.query(Team).order_by(Team.name).all()
    permissions = db.query(Permission).order_by(Permission.slug).all()
    role_permissions = {
        role.id: {
            row.permission.slug
            for row in db.query(RolePermission).filter(RolePermission.role_id == role.id)
        }
        for role in roles
    }
    return render(
        request, "admin/rbac.html", user=user, roles=roles, teams=teams,
        permissions=permissions, role_permissions=role_permissions,
    )


@app.post("/admin/roles")
async def admin_role_save(request: Request, user=Depends(require_role("admin")),
                          db: Session = Depends(get_db)):
    form = await request.form()
    slug = str(form.get("slug", "")).strip()
    if not slug:
        raise HTTPException(400, "Role slug is required")
    role = db.query(Role).filter(Role.slug == slug).first()
    if not role:
        role = Role(slug=slug, name=form.get("name") or slug)
        db.add(role)
        db.flush()
    role.name = form.get("name") or slug
    role.description = form.get("description", "")
    role.inherits = form.getlist("inherits")
    db.query(RolePermission).filter(RolePermission.role_id == role.id).delete()
    for permission_id in form.getlist("permissions"):
        db.add(RolePermission(role_id=role.id, permission_id=int(permission_id)))
    db.commit()
    return RedirectResponse("/admin/rbac", status_code=303)


@app.post("/admin/teams")
async def admin_team_save(request: Request, user=Depends(require_role("admin")),
                          db: Session = Depends(get_db)):
    form = await request.form()
    slug = str(form.get("slug", "")).strip()
    if not slug:
        raise HTTPException(400, "Team slug is required")
    team = db.query(Team).filter(Team.slug == slug).first()
    if not team:
        team = Team(slug=slug, name=form.get("name") or slug)
        db.add(team)
    team.name = form.get("name") or slug
    team.components = [
        value.strip() for value in str(form.get("components", "")).split(",")
        if value.strip()
    ]
    db.commit()
    return RedirectResponse("/admin/rbac", status_code=303)
