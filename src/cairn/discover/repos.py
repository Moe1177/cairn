"""Find git repositories under a workspace folder."""

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from cairn.discover.files import DEFAULT_IGNORE_DIRS

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
    repo_roots = sorted(_find_repo_roots(root, ignore_dirs, max_depth))
    ids = _assign_ids(root, repo_roots)
    locations = (
        RepoLocation(id=repo_id, root=path, app_roots=_app_roots(path, ignore_dirs))
        for path, repo_id in zip(repo_roots, ids, strict=True)
        if repo_id not in ignore_repos
    )
    return tuple(sorted(locations, key=lambda loc: loc.id))


def _children(directory: Path, ignore_dirs: frozenset[str]) -> list[Path]:
    try:
        entries = sorted(directory.iterdir())
    except OSError:
        return []
    return [
        p
        for p in entries
        if p.is_dir() and not p.name.startswith(".") and p.name not in ignore_dirs
    ]


def _find_repo_roots(root: Path, ignore_dirs: frozenset[str], max_depth: int) -> list[Path]:
    found: list[Path] = []
    frontier = [(root, 0)]
    while frontier:
        directory, depth = frontier.pop()
        for child in _children(directory, ignore_dirs):
            if (child / ".git").exists():
                found.append(child)
            elif depth + 1 < max_depth:
                frontier.append((child, depth + 1))
    return found


def _assign_ids(ws_root: Path, roots: list[Path]) -> list[str]:
    counts = Counter(path.name for path in roots)
    return [
        path.name
        if counts[path.name] == 1
        else path.relative_to(ws_root).as_posix().replace("/", "--")
        for path in roots
    ]


def _has_manifest(directory: Path) -> bool:
    return any((directory / name).is_file() for name in MANIFEST_NAMES)


def _app_roots(repo_root: Path, ignore_dirs: frozenset[str]) -> tuple[Path, ...]:
    if _has_manifest(repo_root):
        return (repo_root,)
    found: list[Path] = []
    frontier = [(repo_root, 0)]
    while frontier:
        directory, depth = frontier.pop(0)
        for child in _children(directory, ignore_dirs):
            if (child / ".git").exists():
                continue
            if _has_manifest(child):
                found.append(child)
            elif depth + 1 < _APP_ROOT_SEARCH_DEPTH:
                frontier.append((child, depth + 1))
    return tuple(sorted(found)) or (repo_root,)
