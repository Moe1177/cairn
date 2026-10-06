"""Build, inspect and clear per-repo deep indexes (spec §23). The CLI wires these up."""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from cairn import providers
from cairn.errors import CairnError
from cairn.model.graph import Repo, Workspace
from cairn.providers.base import BuildResult
from cairn.providers.graphify import INSTALL_HINT
from cairn.providers.meta import deep_dir, deep_root, indexed_repos

DEFAULT_TIMEOUT = 900.0
GRAPHIFY_REQUIREMENT = "graphifyy>=0.9.77,<0.10"
BUILD_LOCK = ".building"  # a build in progress (a git hook's background refresh, say)


def graphify_install_command() -> list[str]:
    """How to install graphify beside cairn: as its own tool (uv, else pipx) so cairn's own
    environment isn't touched while it runs (Windows can't replace a running cairn.exe); else
    into the interpreter running cairn."""
    if shutil.which("uv"):
        return ["uv", "tool", "install", GRAPHIFY_REQUIREMENT]
    if shutil.which("pipx"):
        return ["pipx", "install", GRAPHIFY_REQUIREMENT]
    return [sys.executable, "-m", "pip", "install", GRAPHIFY_REQUIREMENT]


def run_installer(command: list[str]) -> int:
    """Run an install command with the user's console (no shell); its exit code."""
    try:
        return subprocess.run(command, check=False).returncode  # noqa: S603 - fixed argv
    except OSError:
        return 127


def select_repos(
    ws_root: Path, workspace: Workspace, names: list[str], *, every: bool, stale: bool
) -> list[Repo]:
    """Named repos, or all of them; `stale` keeps only existing indexes that went out of date."""
    if names:
        repos = [_named(workspace, name) for name in names]
    elif every or stale:
        repos = list(workspace.repos)
    else:
        raise CairnError("name one or more repos, or pass --all or --stale.")
    if not stale:
        return repos
    provider = providers.default_provider()
    kept = []
    for repo in repos:
        status = provider.status(ws_root, repo.id, ws_root / repo.path)
        if status.present and status.stale:
            kept.append(repo)
    return kept


def build(ws_root: Path, repos: list[Repo], *, timeout: float) -> list[BuildResult]:
    if not repos:
        return []
    provider = providers.default_provider()
    if not provider.available():
        raise CairnError(f"graphify isn't installed: {INSTALL_HINT}")
    return [_build_one(provider, ws_root, repo, timeout) for repo in repos]


def _build_one(provider, ws_root: Path, repo: Repo, timeout: float) -> BuildResult:  # type: ignore[no-untyped-def]
    """One build at a time per repo: two quick commits must not run graphify twice at once.
    A lock older than the timeout is a crashed build's and is taken over."""
    lock = deep_dir(ws_root, repo.id) / BUILD_LOCK
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            age = time.time() - lock.stat().st_mtime
        except OSError:
            age = 0.0
        if age < timeout:
            return BuildResult(True, f"{repo.id}: already being built; skipped")
        lock.unlink(missing_ok=True)
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    try:
        return provider.build(ws_root, repo.id, ws_root / repo.path, timeout=timeout)
    finally:
        lock.unlink(missing_ok=True)


def status_lines(ws_root: Path, workspace: Workspace) -> list[str]:
    provider = providers.default_provider()
    lines = []
    for repo_id in indexed_repos(ws_root):
        repo = workspace.repo(repo_id)
        if repo is None:
            lines.append(f"{repo_id}: not in the map any more (`cairn deep clear {repo_id}`)")
            continue
        status = provider.status(ws_root, repo.id, ws_root / repo.path)
        if not status.present:
            lines.append(f"{repo_id}: incomplete (`cairn deep build {repo_id}`)")
            continue
        version = f" {status.version}" if status.version else ""
        built = f" · built at {status.built_sha[:7]}" if status.built_sha else ""
        state = "stale" if status.stale else "fresh"
        lines.append(
            f"{repo_id}: {status.nodes} symbols · {status.provider}{version}{built} · {state}"
        )
    return lines


def clear(ws_root: Path, workspace: Workspace, names: list[str]) -> list[str]:
    """Remove deep indexes. Only directories already under .cairn/deep/ can be named."""
    root = deep_root(ws_root)
    existing = {p.name: p for p in root.iterdir() if p.is_dir()} if root.is_dir() else {}
    targets = [_index_name(workspace, name) for name in names] if names else sorted(existing)
    missing = [t for t in targets if t not in existing]
    if missing:
        raise CairnError(f"no deep index for: {', '.join(missing)}")
    for target in targets:
        shutil.rmtree(existing[target])
    return targets


def _named(workspace: Workspace, name: str) -> Repo:
    lowered = name.strip().lower()
    for repo in workspace.repos:
        if lowered == repo.id.lower() or lowered in (a.lower() for a in repo.aliases):
            return repo
    known = ", ".join(r.id for r in workspace.repos) or "none"
    raise CairnError(f"no repo named {name!r} in the map (repos: {known}).")


def _index_name(workspace: Workspace, name: str) -> str:
    try:
        return _named(workspace, name).id
    except CairnError:
        return name.strip()
