"""Paginated run journal. Filtering and sorting happen in SQL."""

from math import ceil
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from starlette.requests import Request
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, load_only
from database import Run, Scenario, User, Component
from auth.deps import get_current_user, get_db


def create_router(render, require_run_access):
    router = APIRouter()

    @router.get("/journal", response_class=HTMLResponse)
    def journal(
        request: Request,
        user=Depends(get_current_user),
        db: Session = Depends(get_db),
        actor: str = "",
        scenario: str = "",
        group: str = "",
        descendants: bool = True,
        status: str = "",
        q: str = Query("", max_length=200),
        sort: str = "created",
        direction: str = "desc",
        page: int = Query(1, ge=1),
        page_size: int = Query(25, ge=1, le=100),
    ):
        admin = "admin" in (user.roles or [])
        # Prefer immutable run snapshot over the scenario's current group/name.
        group_key = func.coalesce(
            Run.scenario_snapshot["component"].as_string(), Scenario.component, ""
        )
        label = func.coalesce(
            Run.scenario_snapshot["label"].as_string(), Scenario.label, Run.scenario
        )
        query = (
            db.query(
                Run,
                User.username,
                User.full_name,
                group_key.label("group_key"),
                label.label("scenario_label"),
            )
            .outerjoin(User, Run.user_id == User.id)
            .outerjoin(Scenario, Run.scenario == Scenario.slug)
        )
        if not admin:
            query = query.filter(Run.user_id == user.id)
        scope = db.query(Run)
        if not admin:
            scope = scope.filter(Run.user_id == user.id)
        actors = (
            db.query(User.id, User.username, User.full_name)
            .filter(User.id.in_(scope.with_entities(Run.user_id)))
            .order_by(User.username)
            .all()
        )
        scenario_options = [
            r[0]
            for r in scope.with_entities(Run.scenario).distinct().order_by(Run.scenario)
        ]
        components = (
            db.query(Component).order_by(Component.sort_order, Component.label).all()
        )
        by_slug = {c.slug: c for c in components}

        def group_label(slug):
            parts, seen = [], set()
            while slug and slug not in seen:
                seen.add(slug)
                c = by_slug.get(slug)
                parts.append(c.label if c else slug)
                slug = c.parent_group if c else None
            return " / ".join(reversed(parts))

        # Only expose groups represented in the permitted run scope plus ancestors.
        visible = {r[0] for r in query.with_entities(group_key).distinct() if r[0]}
        for slug in list(visible):
            seen = set()
            while slug in by_slug and slug not in seen:
                seen.add(slug)
                slug = by_slug[slug].parent_group
                if slug:
                    visible.add(slug)
        group_options = sorted(
            [(key, group_label(key)) for key in visible], key=lambda x: x[1]
        )
        if actor:
            if actor == "system":
                query = query.filter(or_(Run.user_id.is_(None), Run.user_id == 0))
            elif actor.isdigit():
                query = query.filter(Run.user_id == int(actor))
            else:
                query = query.filter(False)
        if scenario:
            query = query.filter(Run.scenario == scenario)
        if group:
            keys = {group}
            if descendants:
                while True:
                    expanded = keys | {
                        c.slug for c in components if c.parent_group in keys
                    }
                    if expanded == keys:
                        break
                    keys = expanded
            query = query.filter(group_key.in_(keys))
        if status:
            query = query.filter(Run.status == status)
        if q:
            pattern = (
                "%"
                + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                + "%"
            )
            query = query.filter(
                or_(
                    Run.id.ilike(pattern, escape="\\"),
                    Run.scenario.ilike(pattern, escape="\\"),
                    label.ilike(pattern, escape="\\"),
                )
            )
        order_columns = {
            "created": Run.created_at,
            "scenario": label,
            "group": group_key,
            "user": User.username,
            "status": Run.status,
        }
        sort = sort if sort in order_columns else "created"
        direction = direction if direction in {"asc", "desc"} else "desc"
        total = query.count()
        pages = max(1, ceil(total / page_size))
        page = min(page, pages)
        column = order_columns[sort]
        rows = (
            query.options(
                load_only(
                    Run.id,
                    Run.user_id,
                    Run.scenario,
                    Run.status,
                    Run.created_at,
                    Run.completed_at,
                )
            )
            .order_by(
                column.asc() if direction == "asc" else column.desc(), Run.id.desc()
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        entries = [
            dict(
                run=r,
                username=username
                or (
                    "Система"
                    if not r.user_id
                    else f"Удалённый пользователь #{r.user_id}"
                ),
                full_name=full_name or "",
                group=group_label(key) if key else "—",
                label=name,
            )
            for r, username, full_name, key, name in rows
        ]

        def page_url(number):
            params = dict(request.query_params)
            params["page"] = number
            return "/journal?" + urlencode(params)

        return render(
            request,
            "run_journal.html",
            user=user,
            entries=entries,
            actors=actors,
            scenarios=scenario_options,
            groups=group_options,
            actor=actor,
            scenario=scenario,
            group=group,
            descendants=descendants,
            status=status,
            q=q,
            sort=sort,
            direction=direction,
            page=page,
            pages=pages,
            page_size=page_size,
            total=total,
            page_url=page_url,
            admin=admin,
        )

    @router.get("/journal/{run_id}", response_class=HTMLResponse)
    def journal_run(
        run_id: str,
        request: Request,
        user=Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        run = require_run_access(db, user, run_id)
        return render(request, "run_page.html", user=user, run=run)

    return router
