"""Dynamic sources for scenario form inputs."""
from __future__ import annotations

from copy import deepcopy
import os
import time

import httpx

FORGEJO_URL = os.getenv("FORGEJO_URL", "https://forgejo.example.internal").rstrip("/")
FORGEJO_TOKEN = os.getenv("FORGEJO_TOKEN", "")
FORGEJO_OWNER = os.getenv("FORGEJO_OWNER", "example")
VERIFY_TLS = os.getenv("FORGEJO_VERIFY_TLS", "true").lower() != "false"
CACHE_TTL = float(os.getenv("INPUT_SOURCE_CACHE_TTL", "30"))

_BRANCH_CACHE: dict[tuple[str, str], tuple[float, list[str]]] = {}


class InputSourceError(RuntimeError):
    """A dynamic input source could not be resolved."""


def _forgejo_headers() -> dict[str, str]:
    return {
        "Authorization": f"token {FORGEJO_TOKEN}",
        "Accept": "application/json",
    }


def _forgejo_target(scenario: dict, source: dict) -> tuple[str, str]:
    """Resolve repository with priority: source.repo -> source.step -> build step."""
    owner = source.get("owner")
    repo = source.get("repo")

    if repo:
        return str(owner or FORGEJO_OWNER), str(repo)

    step_id = source.get("step") or "build"
    step = next(
        (item for item in scenario.get("steps", []) if item.get("id") == step_id),
        None,
    )
    if not step:
        raise InputSourceError(
            f"git_branches source has no repo and scenario has no step {step_id!r}"
        )
    if step.get("spider") != "forgejo":
        raise InputSourceError(
            f"source step {step_id!r} uses spider {step.get('spider')!r}, "
            "expected 'forgejo'"
        )

    step_with = step.get("with") or {}
    repo = step_with.get("repo")
    owner = owner or step_with.get("owner")
    if not repo:
        raise InputSourceError(f"source step {step_id!r} does not define with.repo")

    return str(owner or FORGEJO_OWNER), str(repo)


def _git_branches(owner: str, repo: str) -> list[str]:
    cache_key = (owner, repo)
    cached = _BRANCH_CACHE.get(cache_key)
    now = time.monotonic()
    if cached and now - cached[0] < CACHE_TTL:
        return list(cached[1])

    url = f"{FORGEJO_URL}/api/v1/repos/{owner}/{repo}/branches"
    branches: list[str] = []
    page = 1
    limit = 100

    while True:
        try:
            response = httpx.get(
                url,
                headers=_forgejo_headers(),
                params={"page": page, "limit": limit},
                timeout=10,
                verify=VERIFY_TLS,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, httpx.HTTPStatusError):
                try:
                    detail = exc.response.json()
                except ValueError:
                    detail = exc.response.text
                raise InputSourceError(
                    f"Forgejo API {exc.response.status_code} while listing "
                    f"{owner}/{repo} branches: {detail!r}"
                ) from exc
            raise InputSourceError(
                f"Forgejo branch lookup failed for {owner}/{repo}: {exc}"
            ) from exc

        if not isinstance(payload, list):
            raise InputSourceError(
                f"Forgejo branch list for {owner}/{repo} returned "
                f"{type(payload).__name__}, expected list"
            )

        for item in payload:
            if isinstance(item, dict) and item.get("name"):
                branches.append(str(item["name"]))

        if len(payload) < limit:
            break
        page += 1

    _BRANCH_CACHE[cache_key] = (now, branches)
    return list(branches)


def resolve_options(scenario: dict, param: dict) -> list[str]:
    source = param.get("source")
    if not isinstance(source, dict):
        raise InputSourceError("dynamic select source must be a mapping")

    source_type = source.get("type")
    if source_type == "git_branches":
        owner, repo = _forgejo_target(scenario, source)
        return _git_branches(owner, repo)

    raise InputSourceError(f"unknown input source type: {source_type!r}")


def enrich_scenario_inputs(scenario: dict) -> dict:
    """Resolve dynamic select options without mutating the stored definition."""
    result = deepcopy(scenario)

    for param in result.get("params", []):
        if param.get("type") != "select" or not param.get("source"):
            continue
        try:
            param["options"] = resolve_options(result, param)
        except InputSourceError as exc:
            param["options"] = []
            param["source_error"] = str(exc)
        except Exception as exc:  # noqa: BLE001
            param["options"] = []
            param["source_error"] = f"dynamic input lookup failed: {exc}"

    return result
