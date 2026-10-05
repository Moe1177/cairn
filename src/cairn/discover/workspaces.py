"""Packages inside a monorepo (spec §21.4): npm/yarn/pnpm, Cargo, go.work and uv workspaces.

Globs are expanded inside the repo only, never through links and never into ignored folders
such as node_modules, and the result is capped so a hostile repo can't make it explode.
"""

import json
import re
import tomllib
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

import yaml

from cairn.discover.files import DEFAULT_IGNORE_DIRS, is_link, read_text

MAX_PACKAGES = 200
_MAX_CANDIDATES = 2000
_MAX_DEPTH = 4
_GLOB_CHARS = frozenset("*?[")
_GO_USE = re.compile(r"use\s+(\S+)")


@dataclass(frozen=True)
class WorkspacePackage:
    name: str
    path: str  # relative to the repo root, POSIX
    stack: tuple[str, ...]


def workspace_packages(repo_root: Path, max_bytes: int = 1_000_000) -> tuple[WorkspacePackage, ...]:
    include, exclude = _patterns(repo_root, max_bytes)
    found: dict[str, Path] = {}
    for pattern in include:
        for directory in _expand(repo_root, pattern):
            rel = directory.relative_to(repo_root).as_posix()
            if not any(fnmatch(rel, ex) for ex in exclude):
                found.setdefault(rel, directory)
        if len(found) >= _MAX_CANDIDATES:
            break
    packages = (_describe(found[rel], rel, max_bytes) for rel in sorted(found))
    return tuple(p for p in packages if p is not None)[:MAX_PACKAGES]


def _patterns(root: Path, max_bytes: int) -> tuple[list[str], list[str]]:
    raw: list[str] = []
    exclude: list[str] = []
    npm = _json(root / "package.json", max_bytes)
    workspaces = npm.get("workspaces") if isinstance(npm, dict) else None
    if isinstance(workspaces, dict):
        workspaces = workspaces.get("packages")
    raw += _strings(workspaces)
    pnpm = _yaml(root / "pnpm-workspace.yaml", max_bytes)
    raw += _strings(pnpm.get("packages") if isinstance(pnpm, dict) else None)
    cargo = _toml(root / "Cargo.toml", max_bytes).get("workspace", {})
    if isinstance(cargo, dict):
        raw += _strings(cargo.get("members"))
        exclude += _strings(cargo.get("exclude"))
    uv = _toml(root / "pyproject.toml", max_bytes).get("tool", {})
    uv = uv.get("uv", {}).get("workspace", {}) if isinstance(uv, dict) else {}
    if isinstance(uv, dict):
        raw += _strings(uv.get("members"))
        exclude += _strings(uv.get("exclude"))
    raw += _go_work(read_text(root / "go.work", max_bytes) or "")
    include = [p for p in raw if not p.startswith("!")]
    exclude += [p[1:] for p in raw if p.startswith("!")]
    return [_clean(p) for p in include], [_clean(p) for p in exclude]


def _clean(pattern: str) -> str:
    parts = [p for p in pattern.replace("\\", "/").split("/") if p and p != "."]
    return "/".join(parts)


def _expand(root: Path, pattern: str) -> list[Path]:
    parts = pattern.split("/") if pattern else []
    if not parts or ".." in parts:
        return []
    current = [root]
    for part in parts:
        following: list[Path] = []
        for directory in current:
            if part == "**":
                following += _descendants(directory)
            elif _GLOB_CHARS & set(part):
                following += [c for c in _children(directory) if fnmatch(c.name, part)]
            elif _usable(directory / part):
                following.append(directory / part)
        current = following[:_MAX_CANDIDATES]
    return [d for d in current if d != root and _manifest(d) is not None]


def _descendants(directory: Path) -> list[Path]:
    found = [directory]
    frontier = [(directory, 0)]
    while frontier and len(found) < _MAX_CANDIDATES:
        current, depth = frontier.pop()
        if depth >= _MAX_DEPTH:
            continue
        for child in _children(current):
            found.append(child)
            frontier.append((child, depth + 1))
    return found


def _children(directory: Path) -> list[Path]:
    try:
        entries = sorted(directory.iterdir(), key=lambda p: p.name)
    except OSError:
        return []
    return [p for p in entries if _usable(p)]


def _usable(path: Path) -> bool:
    try:
        return (
            path.is_dir()
            and not is_link(path)
            and not path.name.startswith(".")
            and path.name not in DEFAULT_IGNORE_DIRS
        )
    except OSError:
        return False


def _manifest(directory: Path) -> str | None:
    for name in ("package.json", "Cargo.toml", "go.mod", "pyproject.toml"):
        if (directory / name).is_file() and not is_link(directory / name):
            return name
    return None


def _describe(directory: Path, rel: str, max_bytes: int) -> WorkspacePackage | None:
    manifest = _manifest(directory)
    name: object = None
    stack: tuple[str, ...] = ()
    if manifest == "package.json":
        name = _json(directory / manifest, max_bytes).get("name")
        typed = (directory / "tsconfig.json").is_file()
        stack = ("typescript",) if typed else ("javascript",)
    elif manifest == "Cargo.toml":
        package = _toml(directory / manifest, max_bytes).get("package", {})
        name = package.get("name") if isinstance(package, dict) else None
        stack = ("rust",)
    elif manifest == "go.mod":
        module = re.search(
            r"^module\s+(\S+)", read_text(directory / manifest, max_bytes) or "", re.M
        )
        name = module.group(1).rstrip("/").rsplit("/", 1)[-1] if module else None
        stack = ("go",)
    elif manifest == "pyproject.toml":
        project = _toml(directory / manifest, max_bytes).get("project", {})
        name = project.get("name") if isinstance(project, dict) else None
        stack = ("python",)
    label = name if isinstance(name, str) and name.strip() else rel.rsplit("/", 1)[-1]
    return WorkspacePackage(name=label.strip()[:128], path=rel, stack=stack)


def _go_work(text: str) -> list[str]:
    found: list[str] = []
    in_block = False
    for line in text.splitlines():
        stripped = line.split("//", 1)[0].strip()
        if in_block:
            if stripped.startswith(")"):
                in_block = False
            elif stripped:
                found.append(stripped)
        elif re.fullmatch(r"use\s*\(", stripped):
            in_block = True
        elif match := _GO_USE.fullmatch(stripped):
            found.append(match.group(1))
    return found


def _strings(value: object) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _json(path: Path, max_bytes: int) -> dict:
    try:
        data = json.loads(read_text(path, max_bytes) or "null")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _toml(path: Path, max_bytes: int) -> dict:
    try:
        return tomllib.loads(read_text(path, max_bytes) or "")
    except tomllib.TOMLDecodeError:
        return {}


def _yaml(path: Path, max_bytes: int) -> dict:
    try:
        data = yaml.safe_load(read_text(path, max_bytes) or "")
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}
