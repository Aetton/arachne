"""Arachne — FastAPI entrypoint.

Run: uvicorn main:app --reload  (from api/ dir)
Seeds an 'admin/admin' user on first boot (change immediately).
"""
import os
import json
from datetime import datetime, timezone

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

import database
from database import SessionLocal, User, Team, Run, utcnow
from auth.security import hash_password, verify_password, create_token
from auth.deps import (
    get_db, get_current_user, get_optional_user, require_role, COOKIE_NAME,
)
import config_loader
import run_engine
import runview
from core import switchboard
from pydantic import BaseModel

BASE_DIR = os.path.dirname(__file__)
TEMPLATES_DIR = os.path.join(BASE_DIR, "..", "frontend", "templates")
STATIC_DIR = os.path.join(BASE_DIR, "..", "frontend", "static")

ALL_ROLES = ["admin", "developer", "tester"]

templates = Jinja2Templates(directory=TEMPLATES_DIR)


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    config_loader.reload()
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
    # which scenarios this user can see (via team components; admin = all)
    if "admin" in (user.roles or []):
        scns = config_loader.all_scenarios()
    else:
        comps: list[str] = []
        for tid in (user.teams or []):
            t = db.get(Team, tid)
            if t:
                comps += t.components or []
        scns = config_loader.scenarios_for_components(comps)
    return render(request, "dashboard.html", user=user, scenarios=scns)


# ---------- scenarios ----------
@app.get("/scenarios/{key}/form", response_class=HTMLResponse)
def scenario_form(key: str, request: Request, user=Depends(get_current_user)):
    s = config_loader.get_scenario(key)
    if not s:
        raise HTTPException(404, "Unknown scenario")
    return render(request, "scenario_form.html", user=user, key=key, s=s)


@app.post("/scenarios/{key}/run", response_class=HTMLResponse)
async def scenario_run(key: str, request: Request, user=Depends(get_current_user)):
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

    run_id = run_engine.start_run(user.id, key, params)

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
    return render(request, "admin/user_form.html", user=user, edit=False, u=None,
                  all_roles=ALL_ROLES, all_teams=teams, action="/admin/users")


@app.get("/admin/users/{uid}/edit", response_class=HTMLResponse)
def admin_user_edit(uid: int, request: Request, user=Depends(require_role("admin")),
                    db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404)
    teams = db.query(Team).all()
    return render(request, "admin/user_form.html", user=user, edit=True, u=u,
                  all_roles=ALL_ROLES, all_teams=teams, action=f"/admin/users/{uid}")


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
