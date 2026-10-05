"""Identity detector: aliases a human might use for a repo, plus a README excerpt."""

import re
from collections.abc import Iterable
from pathlib import Path

from cairn.detectors.base import DetectorContext, DetectorResult
from cairn.detectors.manifests import dig, load_json, load_toml, normalize_py, parse_go_mod, project_name

GENERIC_ALIASES = frozenset(
    {
        "my-app", "app", "web", "frontend", "backend", "server", "client", "api", "project",
        "test", "tests", "demo", "main", "src", "core", "lib", "service", "website", "site",
        "package", "root", "monorepo", "template", "starter", "example", "untitled",
    }
)
README_NAMES = ("README.md", "readme.md", "Readme.md", "README.rst", "README.txt", "README")
EXCERPT_MAX = 300
_SKIP_PREFIXES = ("#", "[![", "![", "<", "```", "---", "|", "=")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")


class IdentityDetector:
    id = "identity"

    def run(self, ctx: DetectorContext) -> DetectorResult:
        names: list[str] = []
        for root in ctx.repo.app_roots:
            names += _manifest_names(ctx, root)
        aliases = clean_aliases(names, ctx.repo.id, frozenset(ctx.config.stop_aliases))
        return DetectorResult(aliases=aliases, readme_excerpt=_readme_excerpt(ctx))


def clean_aliases(
    names: Iterable[str], repo_id: str, extra_generic: frozenset[str] = frozenset()
) -> tuple[str, ...]:
    generic = GENERIC_ALIASES | {g.lower() for g in extra_generic}
    aliases = [repo_id]
    seen = {repo_id.lower()}
    for raw in names:
        alias = raw.strip().lower()
        if len(alias) < 2 or alias in generic or alias in seen:
            continue
        aliases.append(alias)
        seen.add(alias)
    return tuple(aliases)


def first_paragraph(text: str) -> str | None:
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        stripped = block.strip()
        if not stripped or stripped.startswith(_SKIP_PREFIXES):
            continue
        flat = " ".join(_MD_LINK.sub(r"\1", stripped).split())
        return flat if len(flat) <= EXCERPT_MAX else flat[: EXCERPT_MAX - 1] + "…"
    return None


def _manifest_names(ctx: DetectorContext, root: Path) -> list[str]:
    max_bytes = ctx.config.max_file_bytes
    names: list[str] = []
    pkg = load_json(root / "package.json", max_bytes)
    name = pkg.get("name") if pkg else None
    if isinstance(name, str):
        names.append(name)
        if name.startswith("@") and "/" in name:
            names.append(name.split("/", 1)[1])
    py_name = project_name(load_toml(root / "pyproject.toml", max_bytes))
    if py_name:
        names.append(normalize_py(py_name))
    go_text = ctx.read(root / "go.mod")
    module = parse_go_mod(go_text)[0] if go_text else None
    if module:
        names += [module, module.rsplit("/", 1)[-1]]
    cargo_name = dig(load_toml(root / "Cargo.toml", max_bytes), "package", "name")
    if isinstance(cargo_name, str):
        names.append(cargo_name)
    return names


def _readme_excerpt(ctx: DetectorContext) -> str | None:
    for directory in dict.fromkeys((ctx.repo.root, *ctx.repo.app_roots)):
        for name in README_NAMES:
            text = ctx.read(directory / name)
            excerpt = first_paragraph(text) if text else None
            if excerpt:
                return excerpt
    return None
