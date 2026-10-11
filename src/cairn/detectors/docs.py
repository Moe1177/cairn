"""Docs detector: top-level docs that name a sibling repo.

A line that runs a sibling's name as a command (`faas-cli deploy`, `$ faas-cli login`, `| cairn
scan`) is how to use a tool, not a sign the two repos depend on each other: it becomes a
doc_command fact, which marks the sibling as a tool, and never a mention on its own.
"""

import re
from pathlib import Path
from typing import NamedTuple

from cairn.detectors.base import DetectorContext, DetectorResult
from cairn.discover.files import is_link
from cairn.model.graph import MAX_EVIDENCE, Evidence, Fact, FactKind
from cairn.security.policy import is_forbidden

DOC_NAMES = frozenset(
    {"readme.md", "readme.rst", "readme.txt", "readme", "claude.md", "agents.md", "gemini.md"}
)
_PLAIN_WORD = re.compile(r"^[a-z]+$")
_CONTEXT = r"(?:repo|repository|service|project|package|app|codebase)"
_MIN_ALIAS_LEN = 3
_FENCES = ("```", "~~~")
# What follows a command name: a flag or a subcommand word.
_ARGUMENT = r"\s+(?:--?[\w-]|[a-z][\w-]*(?![\w./-]))"


class Command(NamedTuple):
    span: re.Pattern[str]  # `faas-cli new` in prose
    shell: re.Pattern[str]  # a code block's `faas-cli deploy`, `| faas-cli login`, `X=1 faas-cli`
    prompt: re.Pattern[str]  # `$ faas-cli login` outside a code block


def command_pattern(alias: str) -> Command:
    """`alias` run as a command. In prose only a code span or a `$ ` prompt says so: a sentence
    may well start with a repo's name ("orders-svc handles refunds")."""
    escaped = re.escape(alias)
    run = rf"(?:[A-Za-z_]\w*=\S*\s+)*{escaped}{_ARGUMENT}"
    return Command(
        span=re.compile(rf"`\s*(?:\$\s*)?{escaped}{_ARGUMENT}"),
        shell=re.compile(rf"^\s*(?:[$>]\s+)?{run}|(?:\||&&|;|\$\()\s*{run}"),
        prompt=re.compile(rf"^\s*\$\s+{run}"),
    )


def runs(command: Command, line: str, *, in_code: bool) -> bool:
    if command.span.search(line):
        return True
    return bool((command.shell if in_code else command.prompt).search(line))


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
            (target, alias_pattern(alias), command_pattern(alias))
            for alias, target in sorted(ctx.alias_table.items())
            if target != ctx.repo.id and len(alias) >= _MIN_ALIAS_LEN and not alias.isdigit()
        ]
        mentions: dict[str, list[Evidence]] = {}
        commands: dict[str, list[Evidence]] = {}
        for path in _doc_files(ctx):
            text = ctx.read(path)
            if text is None:
                continue
            in_code = False
            for line_no, line in enumerate(text.splitlines(), start=1):
                if line.lstrip().startswith(_FENCES):
                    in_code = not in_code
                    continue
                for target, pattern, command in patterns:
                    if not pattern.search(line):
                        continue
                    hits = commands if runs(command, line, in_code=in_code) else mentions
                    bucket = hits.setdefault(target, [])
                    evidence = ctx.evidence(path, line_no, line)
                    if len(bucket) < MAX_EVIDENCE and evidence not in bucket:
                        bucket.append(evidence)
        facts = tuple(
            Fact(kind=kind, value=target, evidence=tuple(evidence))
            for kind, hits in ((FactKind.DOC_MENTION, mentions), (FactKind.DOC_COMMAND, commands))
            for target, evidence in sorted(hits.items())
        )
        return DetectorResult(consumes=facts)


def _doc_files(ctx: DetectorContext) -> list[Path]:
    files: list[Path] = []
    for directory in dict.fromkeys((ctx.repo.root, *ctx.repo.app_roots)):
        try:
            entries = sorted(directory.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        files += [
            p
            for p in entries
            if p.is_file()
            and not is_link(p)
            and p.name.lower() in DOC_NAMES
            and not is_forbidden(p)
        ]
    return files
