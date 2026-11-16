"""Shared template rendering independent of the application entrypoint."""

from pathlib import Path

from fastapi.templating import Jinja2Templates

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
templates = Jinja2Templates(directory=str(FRONTEND_DIR / "templates"))


def render(request, name, **ctx):
    return templates.TemplateResponse(request, name, ctx)
