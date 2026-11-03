"""Load restart-scoped DB settings before importing the ASGI application."""
from settings_registry import apply_startup_overrides


def main() -> None:
    apply_startup_overrides()
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
