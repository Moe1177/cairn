"""Database detector: tables a repo defines (exposes) and queries (consumes)."""

import re
from pathlib import Path

from cairn.detectors.base import DetectorContext, DetectorResult, merge_facts
from cairn.detectors.manifests import dig, parse_toml
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
    {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py", ".go", ".rb", ".java", ".kt", ".rs", ".php", ".cs"}
)
SQL_NOT_TABLES = frozenset(
    {
        "select", "where", "set", "values", "lateral", "unnest", "only", "information_schema",
        "pg_catalog", "dual", "generate_series", "json_each", "jsonb_each",
        "json_array_elements", "jsonb_array_elements", "the", "a", "an", "and", "or", "sub",
    }
)

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
    return Fact(kind=FactKind.DB_TABLE, value=name.lower(), evidence=(ctx.evidence(path, line_no, line),))


def _is_table(name: str) -> bool:
    return name.lower() not in SQL_NOT_TABLES and not name.isdigit()


def _scan_sql(ctx: DetectorContext, path: Path, text: str) -> Found:
    exposes: list[Fact] = []
    consumes: list[Fact] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
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
    for line_no, line in enumerate(text.splitlines(), start=1):
        exposes += [_table(ctx, path, line_no, line, m.group(1)) for m in ORM_TABLE.finditer(line)]
        refs = [m.group(1) for m in SQL_REF.finditer(line)] + [m.group(1) for m in SUPABASE_REF.finditer(line)]
        consumes += [_table(ctx, path, line_no, line, name) for name in refs if _is_table(name)]
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
    project_id = dig(parse_toml(text), "project_id")
    if not isinstance(project_id, str) or not project_id:
        return []
    line_no = next((i for i, line in enumerate(text.splitlines(), 1) if "project_id" in line), 1)
    evidence = ctx.evidence(path, line_no, text.splitlines()[line_no - 1])
    return [Fact(kind=FactKind.DB_PROJECT_REF, value=f"supabase:{project_id}", evidence=(evidence,))]
