"""Parse package manifests. Every parser returns None/empty on malformed input."""

import json
import re
import tomllib
from pathlib import Path
from typing import Any

from cairn.discover.files import read_text

_PEP508_NAME = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_GO_MODULE = re.compile(r"^module\s+(\S+)", re.M)
_GO_REQUIRE_LINE = re.compile(r"^require\s+(\S+)\s+\S+", re.M)
_GO_REQUIRE_OPEN = re.compile(r"require\s*\(\s*$")
_NPM_DEP_SECTIONS = ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")


def parse_json(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def parse_toml(text: str) -> dict[str, Any] | None:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None


def load_json(path: Path, max_bytes: int) -> dict[str, Any] | None:
    text = read_text(path, max_bytes)
    return parse_json(text) if text else None


def load_toml(path: Path, max_bytes: int) -> dict[str, Any] | None:
    text = read_text(path, max_bytes)
    return parse_toml(text) if text else None


def dig(data: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def normalize_py(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def pep508_name(requirement: str) -> str | None:
    match = _PEP508_NAME.match(requirement)
    return match.group(1) if match else None


def requirements_names(text: str) -> tuple[str, ...]:
    names = []
    for line in text.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if not stripped or stripped.startswith("-"):
            continue
        name = pep508_name(stripped)
        if name:
            names.append(name)
    return tuple(dict.fromkeys(names))


def project_name(pyproject: dict[str, Any] | None) -> str | None:
    name = dig(pyproject, "project", "name") or dig(pyproject, "tool", "poetry", "name")
    return name if isinstance(name, str) else None


def pyproject_requirement_names(pyproject: dict[str, Any] | None) -> tuple[str, ...]:
    names: list[str] = []
    deps = dig(pyproject, "project", "dependencies")
    if isinstance(deps, list):
        names += [n for d in deps if isinstance(d, str) and (n := pep508_name(d))]
    optional = dig(pyproject, "project", "optional-dependencies")
    if isinstance(optional, dict):
        for group in optional.values():
            if isinstance(group, list):
                names += [n for d in group if isinstance(d, str) and (n := pep508_name(d))]
    poetry = dig(pyproject, "tool", "poetry", "dependencies")
    if isinstance(poetry, dict):
        names += [k for k in poetry if k.lower() != "python"]
    return tuple(dict.fromkeys(names))


def python_requirement_names(
    pyproject: dict[str, Any] | None, requirements_text: str | None
) -> tuple[str, ...]:
    from_reqs = requirements_names(requirements_text) if requirements_text else ()
    return tuple(dict.fromkeys((*pyproject_requirement_names(pyproject), *from_reqs)))


def npm_dependencies(pkg: dict[str, Any]) -> tuple[str, ...]:
    names: list[str] = []
    for section in _NPM_DEP_SECTIONS:
        deps = pkg.get(section)
        if isinstance(deps, dict):
            names += [k for k in deps if isinstance(k, str)]
    return tuple(dict.fromkeys(names))


def parse_go_mod(text: str) -> tuple[str | None, tuple[str, ...]]:
    module_match = _GO_MODULE.search(text)
    requires = [r for r in _GO_REQUIRE_LINE.findall(text) if r != "("]
    in_block = False  # line-based, not a lazy multi-line regex: linear on hostile input
    for line in text.splitlines():
        stripped = line.strip()
        if not in_block:
            in_block = _GO_REQUIRE_OPEN.match(line) is not None
            continue
        if stripped.startswith(")"):
            in_block = False
            continue
        parts = stripped.split("//", 1)[0].split()
        if len(parts) >= 2:
            requires.append(parts[0])
    return (module_match.group(1) if module_match else None), tuple(dict.fromkeys(requires))
