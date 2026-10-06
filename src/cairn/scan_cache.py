"""Per-repo detector cache: unchanged repos are not re-read (spec §8, §18)."""

import hashlib
import json
import os
from collections.abc import Iterable
from pathlib import Path

from pydantic import ValidationError

import cairn
from cairn.config import CairnConfig
from cairn.detectors.base import DetectorResult
from cairn.discover.git import (
    GitInfo,
    export_git_memo,
    git_command,
    git_env,
    git_remote,
    head_sha,
    import_git_memo,
)
from cairn.discover.proc import run_bytes
from cairn.model.graph import Command, DetectorError, Fact, Frozen, LayoutEntry, Package
from cairn.paths import repo_cache_dir
from cairn.store.atomic import atomic_write_text

GIT_MEMO = "git-memo.json"
CACHE_VERSION = 4  # bump whenever a cached detector's output changes


class CachedResult(Frozen):
    exposes: tuple[Fact, ...] = ()
    consumes: tuple[Fact, ...] = ()
    aliases: tuple[str, ...] = ()
    stack: tuple[str, ...] = ()
    commands: tuple[Command, ...] = ()
    layout: tuple[LayoutEntry, ...] = ()
    readme_excerpt: str | None = None
    packages: tuple[Package, ...] = ()


class CacheEntry(Frozen):
    version: int = CACHE_VERSION
    key: str
    identity: CachedResult
    relation: CachedResult
    errors: tuple[DetectorError, ...] = ()
    # Repo-relative files the live detectors' filters match (None: walk on a warm refresh).
    live_files: tuple[str, ...] | None = None
    # (folder, mtime) of every folder the walk saw: checks live_files without walking.
    live_dirs: tuple[tuple[str, int], ...] | None = None


def to_cached(result: DetectorResult) -> CachedResult:
    return CachedResult(**{name: getattr(result, name) for name in CachedResult.model_fields})


def from_cached(cached: CachedResult) -> DetectorResult:
    return DetectorResult(**{name: getattr(cached, name) for name in CachedResult.model_fields})


# Untracked files inside a submodule are its business: `-uno` never reported them as dirty.
_STATUS = [
    "status",
    "--porcelain=v1",
    "-z",
    "--untracked-files=all",
    "--ignore-submodules=untracked",
]


def _changed_paths(raw: bytes) -> list[str]:
    """Paths from `git status --porcelain=v1 -z`; a rename/copy record carries its source next."""
    paths: list[str] = []
    records = iter(raw.split(b"\0"))
    for record in records:
        if len(record) < 4:
            continue
        paths.append(os.fsdecode(record[3:]))
        if record[:1] in (b"R", b"C") or record[1:2] in (b"R", b"C"):
            next(records, None)  # the old name, which no longer exists
    return paths


def worktree_fingerprint(root: Path, timeout: float = 10.0) -> str | None:
    """Hash of `git status` plus each listed file's mtime/size; None when git can't answer."""
    status = _status(root, timeout)
    return None if status is None else _digest(root, status)


def repo_state(root: Path, timeout: float = 10.0) -> tuple[GitInfo, str | None]:
    """git_info() and worktree_fingerprint() from three git processes instead of five: the
    dirty flag comes from the fingerprint's own status listing."""
    head = head_sha(root)
    remote = git_remote(root)
    status = _status(root, timeout)
    info = GitInfo(
        head_sha=head or None,
        remote=remote,
        dirty=None if status is None else _tracked_changes(status),
    )
    return info, None if status is None else _digest(root, status)


def _status(root: Path, timeout: float) -> bytes | None:
    # Raw bytes and -z: no C-quoting of non-ASCII names, no console-codepage decoding.
    command = [*git_command(root), "-c", "core.quotePath=false", *_STATUS]
    done = run_bytes(command, timeout=timeout, env=git_env())
    return done[1] if done is not None and done[0] == 0 else None


def _digest(root: Path, stdout: bytes) -> str:
    digest = hashlib.sha1(stdout)
    for rel in _changed_paths(stdout):
        try:
            stat = (root / rel).stat()
            entry = f"\n{rel}:{stat.st_mtime_ns}:{stat.st_size}"
        except (OSError, ValueError):
            entry = f"\n{rel}:gone"
        digest.update(entry.encode("utf-8", "surrogateescape"))
    return digest.hexdigest()


def _tracked_changes(raw: bytes) -> bool:
    """What `git status --porcelain -uno` reports as dirty: any record that isn't untracked."""
    records = iter(raw.split(b"\0"))
    for record in records:
        if len(record) < 4:
            continue
        if record[:2] != b"??":
            return True
    return False


def cache_key(head_sha: str | None, fingerprint: str | None, config: CairnConfig) -> str | None:
    if not head_sha or fingerprint is None:
        return None
    raw = f"{CACHE_VERSION}|{cairn.__version__}|{head_sha}|{fingerprint}|{config.model_dump_json()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def load_entry(ws_root: Path, repo_id: str, key: str) -> CacheEntry | None:
    path = repo_cache_dir(ws_root) / f"{repo_id}.json"
    try:
        entry = CacheEntry.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError):
        return None
    return entry if entry.key == key and entry.version == CACHE_VERSION else None


def save_entry(ws_root: Path, repo_id: str, entry: CacheEntry) -> None:
    atomic_write_text(repo_cache_dir(ws_root) / f"{repo_id}.json", entry.model_dump_json())


def load_git_memo(ws_root: Path) -> None:
    """Prime the git memo from the last scan; a missing or bad file just means asking git."""
    try:
        data = json.loads((repo_cache_dir(ws_root).parent / GIT_MEMO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    import_git_memo(data)


def save_git_memo(ws_root: Path, roots: Iterable[Path]) -> None:
    path = repo_cache_dir(ws_root).parent / GIT_MEMO
    atomic_write_text(path, json.dumps(export_git_memo(roots), sort_keys=True))
