"""Per-repo detector cache: unchanged repos are not re-read (spec §8, §18)."""

import hashlib
import subprocess
from pathlib import Path

from pydantic import ValidationError

import cairn
from cairn.config import CairnConfig
from cairn.detectors.base import DetectorResult
from cairn.model.graph import Command, DetectorError, Fact, Frozen, LayoutEntry
from cairn.paths import repo_cache_dir
from cairn.store.atomic import atomic_write_text

CACHE_VERSION = 1


class CachedResult(Frozen):
    exposes: tuple[Fact, ...] = ()
    consumes: tuple[Fact, ...] = ()
    aliases: tuple[str, ...] = ()
    stack: tuple[str, ...] = ()
    commands: tuple[Command, ...] = ()
    layout: tuple[LayoutEntry, ...] = ()
    readme_excerpt: str | None = None


class CacheEntry(Frozen):
    version: int = CACHE_VERSION
    key: str
    identity: CachedResult
    relation: CachedResult
    errors: tuple[DetectorError, ...] = ()


def to_cached(result: DetectorResult) -> CachedResult:
    return CachedResult(**{name: getattr(result, name) for name in CachedResult.model_fields})


def from_cached(cached: CachedResult) -> DetectorResult:
    return DetectorResult(**{name: getattr(cached, name) for name in CachedResult.model_fields})


def worktree_fingerprint(root: Path, timeout: float = 10.0) -> str | None:
    """Hash of `git status` plus each listed file's mtime/size; None when git can't answer."""
    try:
        done = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    parts = [done.stdout]
    for line in done.stdout.splitlines():
        rel = line[3:].split(" -> ")[-1].strip().strip('"')
        try:
            stat = (root / rel).stat()
            parts.append(f"{rel}:{stat.st_mtime_ns}:{stat.st_size}")
        except OSError:
            parts.append(f"{rel}:gone")
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()


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
