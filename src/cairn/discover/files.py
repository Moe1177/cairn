"""Walk and read repository files safely and deterministically."""

import os
import stat
from collections.abc import Callable, Iterator
from pathlib import Path

import pathspec

from cairn.security.policy import is_forbidden

DEFAULT_IGNORE_DIRS = frozenset(
    {
        ".git",
        ".cairn",
        "node_modules",
        ".venv",
        "venv",
        "dist",
        "build",
        ".next",
        "target",
        "vendor",
        "graphify-out",
        "__pycache__",
        ".turbo",
        ".cache",
        "coverage",
        "fixtures",
        "__fixtures__",
        "testdata",
    }
)
_BINARY_SNIFF_BYTES = 8192
_GITIGNORE_MAX = 1_000_000
# Windows reparse tags for symlinks and junctions. Other reparse points (OneDrive
# placeholders, dedup) are ordinary files and must still be read.
_LINK_TAGS = frozenset({0xA000000C, 0xA0000003})


def is_link(path: Path) -> bool:
    """A symlink, or a Windows junction. Never followed inside a repo (spec §20.1)."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISLNK(info.st_mode) or getattr(info, "st_reparse_tag", 0) in _LINK_TAGS


def crosses_link(root: Path, path: Path) -> bool:
    """True when any existing component of `path` below `root` is a link."""
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        if is_link(current):
            return True
    return False


def iter_files(
    root: Path,
    *,
    ignore_dirs: frozenset[str] = DEFAULT_IGNORE_DIRS,
    max_bytes: int = 1_000_000,
    match: Callable[[str], bool] | None = None,
) -> Iterator[Path]:
    spec = _gitignore_spec(root)
    for dirpath, dirnames, filenames in os.walk(root, onerror=_ignore_error):
        current = Path(dirpath)
        rel_parent = current.relative_to(root).as_posix()
        rel_parent = "" if rel_parent == "." else rel_parent
        dirnames[:] = sorted(
            d for d in dirnames if _keep_dir(current, d, rel_parent, ignore_dirs, spec)
        )
        for name in sorted(filenames):
            if match is not None and not match(name):
                continue
            rel = f"{rel_parent}/{name}" if rel_parent else name
            if spec is not None and spec.match_file(rel):
                continue
            path = current / name
            if is_forbidden(path) or is_link(path):
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size <= max_bytes:
                yield path


def read_text(path: Path, max_bytes: int = 1_000_000) -> str | None:
    if is_forbidden(path) or is_link(path):
        return None
    try:
        with path.open("rb") as handle:
            data = handle.read(max_bytes + 1)
    except OSError:
        return None
    if len(data) > max_bytes or b"\x00" in data[:_BINARY_SNIFF_BYTES]:
        return None
    return data.decode("utf-8", errors="replace").removeprefix("﻿")


def safe_exists(path: Path) -> bool:
    """Path.exists() that treats unreadable paths (e.g. EACCES) as absent instead of raising."""
    try:
        return path.exists()
    except OSError:
        return False


def safe_is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def safe_is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _keep_dir(
    parent: Path,
    name: str,
    rel_parent: str,
    ignore_dirs: frozenset[str],
    spec: pathspec.PathSpec | None,
) -> bool:
    if name in ignore_dirs or is_link(parent / name) or safe_exists(parent / name / ".git"):
        return False
    rel = f"{rel_parent}/{name}/" if rel_parent else f"{name}/"
    return not (spec is not None and spec.match_file(rel))


def _gitignore_spec(root: Path) -> pathspec.PathSpec | None:
    gitignore = root / ".gitignore"
    if not safe_is_file(gitignore):
        return None
    try:
        with gitignore.open("rb") as handle:  # capped: a hostile repo can't make us read GBs
            lines = handle.read(_GITIGNORE_MAX).decode("utf-8", errors="replace").splitlines()
    except OSError:
        return None
    return pathspec.GitIgnoreSpec.from_lines(lines)


def _ignore_error(_error: OSError) -> None:
    return None
