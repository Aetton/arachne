"""Git-backed resolver for Ansible playbooks.

The connector is intentionally small: one repository, one ref, one subdir, one
local cache. It does not manage inventories, schedules, credentials or task
catalogues. Those remain Ansible's and Arachne's jobs.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading


_SHA = re.compile(r"^[0-9a-f]{40}$")
_LOCK = threading.Lock()


class PlaybookRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResolvedPlaybook:
    path: str
    repo: str
    ref: str
    sha: str
    relative_path: str


class PlaybookRepository:
    """Resolve playbooks from a Git repository into immutable cached worktrees."""

    def __init__(
        self,
        repo_url: str,
        *,
        default_ref: str = "main",
        subdir: str = "playbooks",
        cache_dir: str = "/var/cache/arachne/playbooks",
    ):
        self.repo_url = str(repo_url or "").strip()
        self.default_ref = str(default_ref or "main").strip() or "main"
        self.subdir = str(subdir or "").strip().strip("/")
        self.cache_dir = Path(cache_dir).expanduser()

    @classmethod
    def from_env(cls) -> "PlaybookRepository | None":
        repo_url = os.getenv("ANSIBLE_PLAYBOOK_REPO_URL", "").strip()
        if not repo_url:
            return None
        return cls(
            repo_url,
            default_ref=os.getenv("ANSIBLE_PLAYBOOK_REPO_REF", "main"),
            subdir=os.getenv("ANSIBLE_PLAYBOOK_REPO_SUBDIR", "playbooks"),
            cache_dir=os.getenv(
                "ANSIBLE_PLAYBOOK_CACHE_DIR",
                "/var/cache/arachne/playbooks",
            ),
        )

    def probe(self, *, ref: str | None = None) -> dict[str, str]:
        """Fetch the repository and verify that ref/subdir are usable."""
        if not self.repo_url:
            raise PlaybookRepositoryError("playbook repository URL is empty")
        if shutil.which("git") is None:
            raise PlaybookRepositoryError("git executable is not available")

        requested_ref = str(ref or self.default_ref).strip() or self.default_ref
        with _LOCK:
            mirror = self._ensure_mirror()
            self._fetch(mirror)
            sha = self._resolve_sha(mirror, requested_ref)
            checkout = self._ensure_worktree(mirror, sha)

        root = checkout / self.subdir if self.subdir else checkout
        if not root.is_dir():
            raise PlaybookRepositoryError(
                f"repository subdir {self.subdir!r} does not exist in {self.repo_url}@{requested_ref}"
            )
        return {
            "repo": self.repo_url,
            "ref": requested_ref,
            "sha": sha,
            "subdir": self.subdir,
            "path": str(root.resolve()),
        }

    def list_refs(self) -> list[str]:
        """Return branch and tag names visible after a fresh fetch."""
        if not self.repo_url:
            raise PlaybookRepositoryError("playbook repository URL is empty")
        if shutil.which("git") is None:
            raise PlaybookRepositoryError("git executable is not available")

        with _LOCK:
            mirror = self._ensure_mirror()
            self._fetch(mirror)
            proc = self._git(
                "--git-dir",
                str(mirror),
                "for-each-ref",
                "--format=%(refname)",
                "refs/heads",
                "refs/remotes/origin",
                "refs/tags",
            )

        refs: set[str] = set()
        for raw in proc.stdout.splitlines():
            raw = raw.strip()
            if raw.startswith("refs/heads/"):
                refs.add(raw[len("refs/heads/"):])
            elif raw.startswith("refs/remotes/origin/"):
                name = raw[len("refs/remotes/origin/"):]
                if name != "HEAD":
                    refs.add(name)
            elif raw.startswith("refs/tags/"):
                refs.add(raw[len("refs/tags/"):])

        ordered = sorted(refs)
        if self.default_ref in ordered:
            ordered.remove(self.default_ref)
            ordered.insert(0, self.default_ref)
        elif self.default_ref:
            ordered.insert(0, self.default_ref)
        return ordered

    def list_playbooks(self, *, ref: str | None = None) -> dict[str, object]:
        """Return YAML playbooks under the configured subdir for one revision."""
        info = self.probe(ref=ref)
        root = Path(info["path"])
        playbooks = sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in {".yml", ".yaml"}
        )
        return {
            "repo": info["repo"],
            "ref": info["ref"],
            "sha": info["sha"],
            "subdir": info["subdir"],
            "playbooks": playbooks,
        }

    def resolve(self, playbook: str, *, ref: str | None = None) -> ResolvedPlaybook:
        relative = self._safe_relative(playbook)
        info = self.probe(ref=ref)
        checkout = self._worktrees_path() / info["sha"]
        root = checkout / self.subdir if self.subdir else checkout

        candidate = (root / relative).resolve()
        root_resolved = root.resolve()
        try:
            candidate.relative_to(root_resolved)
        except ValueError as exc:
            raise PlaybookRepositoryError(
                f"playbook path escapes repository subdir: {playbook!r}"
            ) from exc
        if not candidate.is_file():
            raise PlaybookRepositoryError(
                f"playbook {relative!r} not found in {self.repo_url}@{info['ref']}"
            )

        return ResolvedPlaybook(
            path=str(candidate),
            repo=self.repo_url,
            ref=info["ref"],
            sha=info["sha"],
            relative_path=str(Path(self.subdir) / relative) if self.subdir else relative,
        )

    def _repo_key(self) -> str:
        tail = self.repo_url.rstrip("/").rsplit("/", 1)[-1]
        if ":" in tail:
            tail = tail.rsplit(":", 1)[-1]
        if tail.endswith(".git"):
            tail = tail[:-4]
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", tail).strip("-.") or "playbooks"
        digest = hashlib.sha256(self.repo_url.encode("utf-8")).hexdigest()[:10]
        return f"{safe}-{digest}"

    def _mirror_path(self) -> Path:
        return self.cache_dir / self._repo_key() / "repo.git"

    def _worktrees_path(self) -> Path:
        return self.cache_dir / self._repo_key() / "worktrees"

    def _ensure_mirror(self) -> Path:
        mirror = self._mirror_path()
        if mirror.exists():
            self._git("--git-dir", str(mirror), "remote", "set-url", "origin", self.repo_url)
            return mirror
        mirror.parent.mkdir(parents=True, exist_ok=True)
        self._git("clone", "--mirror", self.repo_url, str(mirror))
        return mirror

    def _fetch(self, mirror: Path) -> None:
        self._git("--git-dir", str(mirror), "fetch", "--prune", "origin")

    def _resolve_sha(self, mirror: Path, ref: str) -> str:
        candidates = [ref]
        if not _SHA.match(ref):
            candidates += [f"refs/heads/{ref}", f"refs/remotes/origin/{ref}", f"refs/tags/{ref}"]
        for candidate in candidates:
            proc = self._git(
                "--git-dir",
                str(mirror),
                "rev-parse",
                "--verify",
                f"{candidate}^{{commit}}",
                check=False,
            )
            sha = proc.stdout.strip()
            if proc.returncode == 0 and _SHA.match(sha):
                return sha
        raise PlaybookRepositoryError(f"cannot resolve playbook repository ref {ref!r}")

    def _ensure_worktree(self, mirror: Path, sha: str) -> Path:
        worktrees = self._worktrees_path()
        worktrees.mkdir(parents=True, exist_ok=True)
        checkout = worktrees / sha
        if checkout.is_dir():
            return checkout

        try:
            self._git(
                "--git-dir",
                str(mirror),
                "worktree",
                "add",
                "--detach",
                str(checkout),
                sha,
            )
        except PlaybookRepositoryError:
            if checkout.is_dir():
                return checkout
            shutil.rmtree(checkout, ignore_errors=True)
            raise
        return checkout

    @staticmethod
    def _safe_relative(playbook: str) -> str:
        raw = str(playbook or "").strip()
        if not raw:
            raise PlaybookRepositoryError("playbook path is empty")
        path = Path(raw)
        if path.is_absolute() or ".." in path.parts:
            raise PlaybookRepositoryError(f"unsafe playbook path: {raw!r}")
        return path.as_posix()

    @staticmethod
    def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            ["git", *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            check=False,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        if check and proc.returncode != 0:
            message = proc.stderr.strip() or proc.stdout.strip() or "git command failed"
            raise PlaybookRepositoryError(message)
        return proc
