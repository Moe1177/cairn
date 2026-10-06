"""Database detector: tables a repo defines (exposes) and queries (consumes)."""

import bisect
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
_CODE_GATE = ("Table(", "FROM", "JOIN", "INTO", "UPDATE", "model", "ollection(")
# MongoDB (only in files that import mongoose/mongodb: Firestore's v8 API also has
# `db.collection("x")`). A Mongoose model owns its collection, named by mongoose_collection()
# unless a third argument names it; driver `.collection("x")` calls use one.
_MONGO_MARKERS = ("mongoose", "mongodb", "MongoClient")
_MONGOOSE_MODEL = re.compile(
    r"""\b(?:mongoose\.)?model(?:<[^>\n]{0,200}>)?\(\s*['"`]([A-Za-z_][\w-]{0,99})['"`]\s*,"""
    r"""\s*[\w.]{1,100}\s*(?:,\s*['"`]([A-Za-z_][\w.-]{0,99})['"`])?"""
)
_MONGO_COLLECTION = re.compile(
    r"""\.(?:collection|getCollection)\(\s*['"`]([A-Za-z_][\w.-]{0,99})['"`]\s*\)"""
)
_IRREGULAR = {
    "person": "people",
    "child": "children",
    "man": "men",
    "woman": "women",
    "mouse": "mice",
}
_UNCOUNTABLE = frozenset({"info", "data", "news", "equipment", "information", "money", "series"})
ORM_TABLE = re.compile(r"\b(?:pgTable|mysqlTable|sqliteTable)\(\s*['\"`]([A-Za-z_]\w*)['\"`]")
SUPABASE_REF = re.compile(
    r"\.from\(\s*['\"`]([A-Za-z_]\w*)['\"`]\s*\)\s*\.\s*(?:select|insert|update|upsert|delete)\b"
)
# Real files define or touch at most a few hundred tables; a hostile one can't make cairn
# build an unbounded number of facts (spec §20.1).
MAX_FACTS_PER_FILE = 2000
PRISMA_MODEL = re.compile(r"\s*model\s+(\w+)\s*\{")
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


def mongoose_collection(model: str) -> str:
    """The collection Mongoose stores a model in: lowercased and pluralised like its own
    (simplified) rules. "User" -> users, "CheckIn" -> checkins, "Category" -> categories."""
    name = model.lower()
    if name in _UNCOUNTABLE or name.endswith("s"):
        return name
    if name in _IRREGULAR:
        return _IRREGULAR[name]
    if name.endswith("y") and len(name) > 1 and name[-2] not in "aeiou":
        return name[:-1] + "ies"
    if name.endswith(("x", "ch", "sh")):
        return name + "es"
    return name + "s"


def _table(ctx: DetectorContext, path: Path, line_no: int, line: str, name: str) -> Fact:
    return Fact(
        kind=FactKind.DB_TABLE, value=name.lower(), evidence=(ctx.evidence(path, line_no, line),)
    )


_LINE_COMMENT_PREFIXES = ("//", "#", "--")


def _code_lines(text: str) -> Iterator[tuple[int, str]]:
    """Yield (line_no, line) for lines that aren't comments (spec §16.4).

    Line comments are skipped, and so is everything inside /* ... */ blocks (JSDoc).
    A line that merely starts with `*` outside a block is code (the tail of a `SELECT *`).
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
        if len(exposes) + len(consumes) >= MAX_FACTS_PER_FILE:
            break
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
    mongo = any(marker in text for marker in _MONGO_MARKERS)
    for line_no, line in _code_lines(text):
        if len(exposes) + len(consumes) >= MAX_FACTS_PER_FILE:
            return exposes, consumes
        if not any(key in line for key in _CODE_GATE):
            continue  # ORM_TABLE needs `Table(`; SQL_REF needs an upper-case keyword
        exposes += [_table(ctx, path, line_no, line, m.group(1)) for m in ORM_TABLE.finditer(line)]
        refs = [m.group(1) for m in SQL_REF.finditer(line)]
        consumes += [_table(ctx, path, line_no, line, name) for name in refs if _is_table(name)]
        if mongo:
            exposes += [
                _table(ctx, path, line_no, line, m.group(2) or mongoose_collection(m.group(1)))
                for m in _MONGOOSE_MODEL.finditer(line)
            ]
            consumes += [
                _table(ctx, path, line_no, line, m.group(1))
                for m in _MONGO_COLLECTION.finditer(line)
            ]
    # Query-builder chains are usually split across lines: supabase / .from('t') / .select().
    starts = [0, *(i + 1 for i, ch in enumerate(text) if ch == "\n")]
    for match in SUPABASE_REF.finditer(text):
        if len(exposes) + len(consumes) >= MAX_FACTS_PER_FILE:
            break
        line_no = bisect.bisect_right(starts, match.start(1))
        if _is_table(match.group(1)):
            consumes.append(_table(ctx, path, line_no, lines[line_no - 1], match.group(1)))
    return exposes, consumes


def _scan_prisma(ctx: DetectorContext, path: Path, text: str) -> list[Fact]:
    lines = text.splitlines()
    return [
        _table(ctx, path, line_no, lines[line_no - 1], name)
        for line_no, name in prisma_models(lines)[:MAX_FACTS_PER_FILE]
    ]


def prisma_models(lines: list[str]) -> list[tuple[int, str]]:
    """(line, table) per `model` block, honouring `@@map`. One pass over the lines: a lazy
    multi-line regex goes quadratic on unclosed blocks (spec §20.1)."""
    found: list[tuple[int, str]] = []
    current: tuple[int, str] | None = None
    for line_no, line in enumerate(lines, start=1):
        opened = PRISMA_MODEL.match(line)
        if opened:
            if current:  # an unclosed block: keep it and start the next one
                found.append(current)
            current = (line_no, opened.group(1))
        elif current and line.strip().startswith("}"):
            found.append(current)
            current = None
        elif current and (mapped := PRISMA_MAP.search(line)):
            current = (current[0], mapped.group(1))
    if current:
        found.append(current)
    return found


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
