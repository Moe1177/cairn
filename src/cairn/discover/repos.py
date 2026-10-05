"""Find git repositories under a workspace folder."""

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from cairn.discover.files import (
    DEFAULT_IGNORE_DIRS,
    is_link,
    safe_exists,
    safe_is_dir,
    safe_is_file,
)

MANIFEST_NAMES = (
    "package.json",
    "pyproject.toml",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "setup.py",
    "requirements.txt",
)
_APP_ROOT_SEARCH_DEPTH = 2


@dataclass(frozen=True)
class RepoLocation:
    id: str
    root: Path
    app_roots: tuple[Path, ...]

    def rel_path(self, ws_root: Path) -> str:
        return self.root.relative_to(ws_root).as_posix()


def discover_repos(
    ws_root: Path,
    *,
    ignore_dirs: frozenset[str] = DEFAULT_IGNORE_DIRS,
    max_depth: int = 4,
    ignore_repos: frozenset[str] = frozenset(),
) -> tuple[RepoLocation, ...]:
    root = ws_root.resolve()
    repo_roots = _dedupe_links(_find_repo_roots(root, ignore_dirs, max_depth))
    ids = _assign_ids(root, repo_roots)
    locations = (
        RepoLocation(id=repo_id, root=path, app_roots=_app_roots(path, ignore_dirs))
        for path, repo_id in zip(repo_roots, ids, strict=True)
        if repo_id not in ignore_repos
    )
    return tuple(sorted(locations, key=lambda loc: loc.id))


def _children(directory: Path, ignore_dirs: frozenset[str], *, links: bool = True) -> list[Path]:
    """Sub-folders. Links are followed only at workspace level (a linked repo is still a repo);
    inside a repo they could point anywhere, so app-root discovery passes links=False."""
    try:
        entries = sorted(directory.iterdir(), key=_order)
    except OSError:
        return []
    return [
        p
        for p in entries
        if safe_is_dir(p)
        and not p.name.startswith(".")
        and p.name not in ignore_dirs
        and (links or not is_link(p))
    ]


def _find_repo_roots(root: Path, ignore_dirs: frozenset[str], max_depth: int) -> list[Path]:
    found: list[Path] = []
    frontier = [(root, 0)]
    while frontier:
        directory, depth = frontier.pop()
        for child in _children(directory, ignore_dirs):
            if safe_exists(child / ".git"):
                found.append(child)
            elif depth + 1 < max_depth:
                frontier.append((child, depth + 1))
    return found


def _dedupe_links(paths: list[Path]) -> list[Path]:
    """One entry per real repo: a symlink/junction to a repo yields the real folder (spec §16.4)."""
    unique: dict[Path, Path] = {}
    for path in sorted(paths, key=lambda p: (_real(p) != p, len(p.parts), str(p))):
        unique.setdefault(_real(path), path)
    return sorted(unique.values(), key=_order)


def _order(path: Path) -> str:
    """Windows Paths sort case-insensitively, POSIX ones don't; sort strings instead so every
    OS produces the same map (spec §20.2)."""
    return path.as_posix()


def _real(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path


_UNSAFE_ID = re.compile(r"[\\:\x00-\x1f\x7f-\x9f\u2028\u2029]")


def _assign_ids(ws_root: Path, roots: list[Path]) -> list[str]:
    """Folder names, made safe as file names (macOS stores Finder's "a/b" as "a:b")."""
    names = [_safe_id(path.name) for path in roots]
    counts = Counter(name.lower() for name in names)  # Foo/foo collide on Windows/macOS
    return [
        name if counts[name.lower()] == 1 else _safe_id(path.relative_to(ws_root).as_posix())
        for name, path in zip(names, roots, strict=True)
    ]


def _safe_id(name: str) -> str:
    return _UNSAFE_ID.sub("-", name.replace("/", "--"))[:128] or "repo"


def _has_manifest(directory: Path) -> bool:
    return any(safe_is_file(directory / name) for name in MANIFEST_NAMES)


def _app_roots(repo_root: Path, ignore_dirs: frozenset[str]) -> tuple[Path, ...]:
    if _has_manifest(repo_root):
        return (repo_root,)
    found: list[Path] = []
    frontier = [(repo_root, 0)]
    while frontier:
        directory, depth = frontier.pop(0)
        for child in _children(directory, ignore_dirs, links=False):
            if safe_exists(child / ".git"):
                continue
            if _has_manifest(child):
                found.append(child)
            elif depth + 1 < _APP_ROOT_SEARCH_DEPTH:
                frontier.append((child, depth + 1))
    return tuple(sorted(found, key=_order)) or (repo_root,)
