"""Thin Nexus helper. For raw-hosted repos the download URL is deterministic,
so we just build it — no API round-trip needed for links."""
import os

NEXUS_URL = os.getenv("NEXUS_URL", "https://nexus.redsoft.internal").rstrip("/")


def download_url(repo: str, path: str) -> str:
    return f"{NEXUS_URL}/repository/{repo}/{path.lstrip('/')}"


def artifact_links(artifacts: list[dict]) -> list[dict]:
    out = []
    for a in artifacts:
        out.append({
            "name": a.get("name") or a["path"].rsplit("/", 1)[-1],
            "url": download_url(a["repo"], a["path"]),
            "repo": a["repo"],
        })
    return out
