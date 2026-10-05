"""Database detector: tables a repo defines (exposes) and queries (consumes)."""

import re
from collections.abc import Iterator
from pathlib import Path

from cairn.detectors.base import DetectorContext, DetectorResult, find_line, merge_facts
from cairn.detectors.manifests import (
    dig,
    normalize_py,
    npm_dependencies,
    parse_json,
    parse_toml,
    pyproject_requirement_names,
    requirements_names,
)
from cairn.model.graph import Fact, FactKind

_IDENT = r'"?(?:[A-Za-z_]\w*"?\.)?"?([A-Za-z_]\w*)"?'
CREATE_TABLE = re.compile(r"(?i)\bcreate\s+table\s+(?:if\s+not\s+exists\s+)?" + _IDENT)
SQL_REF = re.compile(r"\b(?:FROM|JOIN|INTO|UPDATE)\s+(?:ONLY\s+)?" + _IDENT)
SQL_REF_ANYCASE = re.compile(SQL_REF.pattern, re.IGNORECASE)
ORM_TABLE = re.compile(r"\b(?:pgTable|mysqlTable|sqliteTable)\(\s*['\"`]([A-Za-z_]\w*)['\"`]")
SUPABASE_REF = re.compile(
    r"\.from\(\s*['\"`]([A-Za-z_]\w*)['\"`]\s*\)\s*\.\s*(?:select|insert|update|upsert|delete)\b"
)
PRISMA_MODEL = re.compile(r"^\s*model\s+(\w+)\s*\{(.*?)^\s*\}", re.M | re.S)
PRISMA_MAP = re.compile(r'@@map\(\s*"([^"]+)"\s*\)')
CODE_SUFFIXES = frozenset(
    {
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".py",
        ".go",
        ".rb",
        ".java",
        ".kt",
        ".rs",
        ".php",
        ".cs",
    }
)
SQL_NOT_TABLES = frozenset(
    {
        "select",
        "where",
        "set",
        "values",
        "lateral",
        "unnest",
        "only",
        "information_schema",
        "pg_catalog",
        "dual",
        "generate_series",
        "json_each",
        "jsonb_each",
        "json_array_elements",
        "jsonb_array_elements",
        "the",
        "a",
        "an",
        "and",
        "or",
        "sub",
        "no",
        "action",
        "cascade",
        "restrict",
        "null",
        "default",
    }
)
_SYSTEM_PREFIXES = ("pg_", "sqlite_")
_LINKED_REF = re.compile(r"[a-z0-9]{8,40}")

Found = tuple[list[Fact], list[Fact]]


class DatabaseDetector:
    id = "database"

    def run(self, ctx: DetectorContext) -> DetectorResult:
        exposes: list[Fact] = []
        consumes: list[Fact] = []
        for path in ctx.files(_wanted):
            text = ctx.read(path)
            if text is None:
                continue
            found_exposes, found_consumes = _scan(ctx, path, text)
            exposes += found_exposes
            consumes += found_consumes
        consumes += _providers(ctx)
        return DetectorResult(exposes=merge_facts(exposes), consumes=merge_facts(consumes))


def _wanted(name: str) -> bool:
    suffix = Path(name).suffix.lower()
    return suffix in CODE_SUFFIXES or suffix in {".sql", ".prisma"} or name == "config.toml"


def _scan(ctx: DetectorContext, path: Path, text: str) -> Found:
    suffix = path.suffix.lower()
    if suffix == ".sql":
        return _scan_sql(ctx, path, text)
    if suffix == ".prisma":
        return _scan_prisma(ctx, path, text), []
    if path.name == "config.toml":
        return [], _scan_supabase(ctx, path, text) if path.parent.name == "supabase" else []
    return _scan_code(ctx, path, text)


def _table(ctx: DetectorContext, path: Path, line_no: int, line: str, name: str) -> Fact:
    return Fact(
        kind=FactKind.DB_TABLE, value=name.lower(), evidence=(ctx.evidence(path, line_no, line),)
    )


_LINE_COMMENT_PREFIXES = ("//", "#", "--")


def _code_lines(text: str) -> Iterator[tuple[int, str]]:
    """Yield (line_no, line) for lines that aren't comments (spec §16.4).

    Line comments are skipped, and so is everything inside /* ... */ blocks (JSDoc).
    A line that merely starts with `*` outside a block is code, e.g. `  * FROM orders`.
    """
    in_block = False
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if in_block:
            in_block = "*/" not in line
            continue
        if stripped.startswith("/*"):
            in_block = "*/" not in stripped[2:]
            continue
        if not stripped.startswith(_LINE_COMMENT_PREFIXES):
            yield line_no, line


def _is_table(name: str) -> bool:
    lowered = name.lower()
    return (
        lowered not in SQL_NOT_TABLES
        and not lowered.startswith(_SYSTEM_PREFIXES)
        and not name.isdigit()
    )


def _scan_sql(ctx: DetectorContext, path: Path, text: str) -> Found:
    exposes: list[Fact] = []
    consumes: list[Fact] = []
    for line_no, line in _code_lines(text):
        created = [m.group(1) for m in CREATE_TABLE.finditer(line)]
        exposes += [_table(ctx, path, line_no, line, name) for name in created if _is_table(name)]
        if created:
            continue
        consumes += [
            _table(ctx, path, line_no, line, m.group(1))
            for m in SQL_REF_ANYCASE.finditer(line)
            if _is_table(m.group(1))
        ]
    return exposes, consumes


def _scan_code(ctx: DetectorContext, path: Path, text: str) -> Found:
    exposes: list[Fact] = []
    consumes: list[Fact] = []
    lines = text.splitlines()
    for line_no, line in _code_lines(text):
        exposes += [_table(ctx, path, line_no, line, m.group(1)) for m in ORM_TABLE.finditer(line)]
        refs = [m.group(1) for m in SQL_REF.finditer(line)]
        consumes += [_table(ctx, path, line_no, line, name) for name in refs if _is_table(name)]
    # Query-builder chains are usually split across lines: supabase / .from('t') / .select().
    for match in SUPABASE_REF.finditer(text):
        line_no = text.count("\n", 0, match.start(1)) + 1
        if _is_table(match.group(1)):
            consumes.append(_table(ctx, path, line_no, lines[line_no - 1], match.group(1)))
    return exposes, consumes


def _scan_prisma(ctx: DetectorContext, path: Path, text: str) -> list[Fact]:
    lines = text.splitlines()
    facts = []
    for match in PRISMA_MODEL.finditer(text):
        mapped = PRISMA_MAP.search(match.group(2))
        name = mapped.group(1) if mapped else match.group(1)
        line_no = text.count("\n", 0, match.start(1)) + 1
        facts.append(_table(ctx, path, line_no, lines[line_no - 1], name))
    return facts


def _scan_supabase(ctx: DetectorContext, path: Path, text: str) -> list[Fact]:
    """Spec §16.3: config.toml holds a *local* id; `supabase link` writes the real project ref."""
    facts: list[Fact] = []
    project_id = dig(parse_toml(text), "project_id")
    if isinstance(project_id, str) and project_id:
        line_no = next(
            (i for i, line in enumerate(text.splitlines(), 1) if "project_id" in line), 1
        )
        evidence = ctx.evidence(path, line_no, text.splitlines()[line_no - 1])
        local = f"supabase-local:{project_id}"
        facts.append(Fact(kind=FactKind.DB_PROJECT_REF, value=local, evidence=(evidence,)))
    ref_path = path.parent / ".temp" / "project-ref"
    linked = (ctx.read(ref_path) or "").strip()
    if _LINKED_REF.fullmatch(linked):
        evidence = ctx.evidence(ref_path, 1, linked)
        facts.append(
            Fact(kind=FactKind.DB_PROJECT_REF, value=f"supabase:{linked}", evidence=(evidence,))
        )
    return facts


# Distinctive hosted-database clients. Name-only table overlap across disjoint providers
# is dropped (spec §16.7). Auth/push SDKs such as firebase are deliberately not listed.
_NPM_PROVIDERS = {
    "@neondatabase/serverless": "neon",
    "@supabase/supabase-js": "supabase",
    "@supabase/ssr": "supabase",
    "@planetscale/database": "planetscale",
    "@libsql/client": "turso",
    "mongodb": "mongodb",
    "mongoose": "mongodb",
}
_PY_PROVIDERS = {
    "supabase": "supabase",
    "pymongo": "mongodb",
    "libsql-client": "turso",
}


def _providers(ctx: DetectorContext) -> list[Fact]:
    facts: list[Fact] = []
    for root in ctx.repo.app_roots:
        facts += _npm_providers(ctx, root / "package.json")
        facts += _py_providers(ctx, root / "pyproject.toml")
        facts += _py_providers(ctx, root / "requirements.txt")
    return facts


def _provider_fact(ctx: DetectorContext, path: Path, text: str, value: str, needle: str) -> Fact:
    line_no, line = find_line(text, needle)
    evidence = (ctx.evidence(path, line_no, line),)
    return Fact(kind=FactKind.DB_PROVIDER, value=value, evidence=evidence)


def _npm_providers(ctx: DetectorContext, path: Path) -> list[Fact]:
    text = ctx.read(path)
    pkg = parse_json(text) if text else None
    if not text or pkg is None:
        return []
    return [
        _provider_fact(ctx, path, text, _NPM_PROVIDERS[dep], f'"{dep}"')
        for dep in npm_dependencies(pkg)
        if dep in _NPM_PROVIDERS
    ]


def _py_providers(ctx: DetectorContext, path: Path) -> list[Fact]:
    text = ctx.read(path)
    if not text:
        return []
    if path.suffix == ".toml":
        names = pyproject_requirement_names(parse_toml(text))
    else:
        names = requirements_names(text)
    return [
        _provider_fact(ctx, path, text, _PY_PROVIDERS[normalize_py(raw)], raw)
        for raw in names
        if normalize_py(raw) in _PY_PROVIDERS
    ]
