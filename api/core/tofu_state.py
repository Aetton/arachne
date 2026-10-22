"""Conservative checks before reusing a local OpenTofu state."""
import json
from pathlib import Path


def ensure_provisionable_state(path: Path) -> None:
    """Allow absent or explicitly empty v4 state; preserve every existing file.

    Call while holding the stand lock, before replacing its module or inputs.
    Outputs alone do not represent managed resources. Nonempty resource lists
    remain blocked, including data sources and resources with zero instances.
    """
    try:
        raw = path.read_text()
    except FileNotFoundError:
        return
    try:
        state = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f"Cannot validate stand state {path}; inspect it before retrying") from exc
    if not isinstance(state, dict) or state.get("version") != 4 or not isinstance(state.get("resources"), list):
        raise ValueError(f"Unknown stand state format at {path}; inspect it before retrying")
    if state["resources"]:
        raise ValueError(
            "Stand state already exists with resources; destroy it before provisioning again"
        )
