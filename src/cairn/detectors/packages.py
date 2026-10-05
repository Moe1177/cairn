"""Packages detector: what each repo publishes and what it depends on."""

from pathlib import Path

from cairn.detectors.base import DetectorContext, DetectorResult, find_line, merge_facts
from cairn.detectors.manifests import (
    dig,
    normalize_py,
    npm_dependencies,
    parse_go_mod,
    parse_json,
    parse_toml,
    project_name,
    pyproject_requirement_names,
    requirements_names,
)
from cairn.model.graph import Fact, FactKind

Found = tuple[list[Fact], list[Fact]]
_CARGO_DEP_SECTIONS = ("dependencies", "dev-dependencies", "build-dependencies")


class PackagesDetector:
    id = "packages"

    def run(self, ctx: DetectorContext) -> DetectorResult:
        exposes: list[Fact] = []
        consumes: list[Fact] = []
        for root in ctx.repo.app_roots:
            for probe in (_npm, _python, _go, _cargo):
                found_exposes, found_consumes = probe(ctx, root)
                exposes += found_exposes
                consumes += found_consumes
        return DetectorResult(exposes=merge_facts(exposes), consumes=merge_facts(consumes))


def _fact(ctx: DetectorContext, path: Path, text: str, value: str, needle: str) -> Fact:
    line_no, line = find_line(text, needle)
    return Fact(kind=FactKind.PACKAGE, value=value, evidence=(ctx.evidence(path, line_no, line),))


def _npm(ctx: DetectorContext, root: Path) -> Found:
    path = root / "package.json"
    text = ctx.read(path)
    pkg = parse_json(text) if text else None
    if text is None or pkg is None:
        return [], []
    name = pkg.get("name")
    exposes = [_fact(ctx, path, text, f"npm:{name}", f'"{name}"')] if isinstance(name, str) else []
    consumes = [_fact(ctx, path, text, f"npm:{dep}", f'"{dep}"') for dep in npm_dependencies(pkg)]
    return exposes, consumes


def _python(ctx: DetectorContext, root: Path) -> Found:
    exposes: list[Fact] = []
    consumes: list[Fact] = []
    py_path = root / "pyproject.toml"
    py_text = ctx.read(py_path)
    pyproject = parse_toml(py_text) if py_text else None
    if py_text and pyproject:
        name = project_name(pyproject)
        if name:
            exposes.append(_fact(ctx, py_path, py_text, f"pypi:{normalize_py(name)}", name))
        consumes += [
            _fact(ctx, py_path, py_text, f"pypi:{normalize_py(raw)}", raw)
            for raw in pyproject_requirement_names(pyproject)
        ]
    req_path = root / "requirements.txt"
    req_text = ctx.read(req_path)
    if req_text:
        consumes += [
            _fact(ctx, req_path, req_text, f"pypi:{normalize_py(raw)}", raw)
            for raw in requirements_names(req_text)
        ]
    return exposes, consumes


def _go(ctx: DetectorContext, root: Path) -> Found:
    path = root / "go.mod"
    text = ctx.read(path)
    if not text:
        return [], []
    module, requires = parse_go_mod(text)
    exposes = [_fact(ctx, path, text, f"go:{module}", module)] if module else []
    return exposes, [_fact(ctx, path, text, f"go:{req}", req) for req in requires]


def _cargo(ctx: DetectorContext, root: Path) -> Found:
    path = root / "Cargo.toml"
    text = ctx.read(path)
    data = parse_toml(text) if text else None
    if text is None or data is None:
        return [], []
    name = dig(data, "package", "name")
    exposes = [_fact(ctx, path, text, f"cargo:{name}", name)] if isinstance(name, str) else []
    consumes = [
        _fact(ctx, path, text, f"cargo:{dep}", dep)
        for section in _CARGO_DEP_SECTIONS
        if isinstance(data.get(section), dict)
        for dep in data[section]
    ]
    return exposes, consumes
