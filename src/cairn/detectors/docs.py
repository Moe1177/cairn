"""Docs detector: top-level docs that name a sibling repo."""

import re
from pathlib import Path

from cairn.detectors.base import DetectorContext, DetectorResult
from cairn.model.graph import MAX_EVIDENCE, Evidence, Fact, FactKind
from cairn.security.policy import is_forbidden

DOC_NAMES = frozenset(
    {"readme.md", "readme.rst", "readme.txt", "readme", "claude.md", "agents.md", "gemini.md"}
)
_PLAIN_WORD = re.compile(r"^[a-z]+$")
_CONTEXT = r"(?:repo|repository|service|project|package|app|codebase)"
_MIN_ALIAS_LEN = 3


def alias_pattern(alias: str) -> re.Pattern[str]:
    escaped = re.escape(alias)
    bounded = rf"(?<![\w-]){escaped}(?![\w-])"
    if _PLAIN_WORD.match(alias):
        return re.compile(
            rf"`{escaped}`|\.\./{escaped}\b|{bounded}\s+{_CONTEXT}\b|\b{_CONTEXT}\s+{bounded}",
            re.IGNORECASE,
        )
    return re.compile(bounded, re.IGNORECASE)


class DocsDetector:
    id = "docs"

    def run(self, ctx: DetectorContext) -> DetectorResult:
        patterns = [
            (target, alias_pattern(alias))
            for alias, target in sorted(ctx.alias_table.items())
            if target != ctx.repo.id and len(alias) >= _MIN_ALIAS_LEN and not alias.isdigit()
        ]
        hits: dict[str, list[Evidence]] = {}
        for path in _doc_files(ctx):
            text = ctx.read(path)
            if text is None:
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                for target, pattern in patterns:
                    if not pattern.search(line):
                        continue
                    bucket = hits.setdefault(target, [])
                    evidence = ctx.evidence(path, line_no, line)
                    if len(bucket) < MAX_EVIDENCE and evidence not in bucket:
                        bucket.append(evidence)
        facts = tuple(
            Fact(kind=FactKind.DOC_MENTION, value=target, evidence=tuple(evidence))
            for target, evidence in sorted(hits.items())
        )
        return DetectorResult(consumes=facts)


def _doc_files(ctx: DetectorContext) -> list[Path]:
    files: list[Path] = []
    for directory in dict.fromkeys((ctx.repo.root, *ctx.repo.app_roots)):
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            continue
        files += [
            p
            for p in entries
            if p.is_file() and p.name.lower() in DOC_NAMES and not is_forbidden(p)
        ]
    return files
