"""Shared detector types and helpers."""

import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from cairn.config import CairnConfig
from cairn.discover.files import DEFAULT_IGNORE_DIRS, iter_files, read_text
from cairn.discover.repos import RepoLocation
from cairn.model.graph import MAX_EVIDENCE, Command, Evidence, Fact, FactKind, LayoutEntry
from cairn.security.redact import make_snippet

# Test code, fixtures, and examples hold fake data that would create false edges.
NOISE_DIRS = frozenset(
    {
        "tests",
        "test",
        "__tests__",
        "spec",
        "e2e",
        "fixtures",
        "__fixtures__",
        "testdata",
        "test-data",
        "__mocks__",
        "mocks",
        "examples",
        "example",
    }
)
_TEST_FILE = re.compile(r"^test_.*\.py$|_test\.(?:py|go)$|\.(?:test|spec)\.[cm]?[jt]sx?$")


@dataclass(frozen=True)
class DetectorContext:
    workspace_root: Path
    repo: RepoLocation
    config: CairnConfig
    alias_table: Mapping[str, str] = field(default_factory=dict)

    def rel(self, path: Path) -> str:
        return path.relative_to(self.repo.root).as_posix()

    def evidence(self, path: Path, line_no: int, line: str) -> Evidence:
        return Evidence(
            repo=self.repo.id, file=self.rel(path), line=line_no, snippet=make_snippet(line)
        )

    def files(self, match: Callable[[str], bool]) -> Iterator[Path]:
        ignore = DEFAULT_IGNORE_DIRS | NOISE_DIRS | frozenset(self.config.ignore_dirs)
        return iter_files(
            self.repo.root,
            ignore_dirs=ignore,
            max_bytes=self.config.max_file_bytes,
            match=lambda name: match(name) and not _TEST_FILE.search(name),
        )

    def read(self, path: Path) -> str | None:
        return read_text(path, self.config.max_file_bytes)


@dataclass(frozen=True)
class DetectorResult:
    exposes: tuple[Fact, ...] = ()
    consumes: tuple[Fact, ...] = ()
    aliases: tuple[str, ...] = ()
    stack: tuple[str, ...] = ()
    commands: tuple[Command, ...] = ()
    layout: tuple[LayoutEntry, ...] = ()
    readme_excerpt: str | None = None


class Detector(Protocol):
    id: str

    def run(self, ctx: DetectorContext) -> DetectorResult: ...


def merge_facts(facts: Iterable[Fact]) -> tuple[Fact, ...]:
    grouped: dict[tuple[str, str], list[Evidence]] = {}
    for fact in facts:
        bucket = grouped.setdefault((fact.kind.value, fact.value), [])
        for ev in fact.evidence:
            if ev not in bucket and len(bucket) < MAX_EVIDENCE:
                bucket.append(ev)
    return tuple(
        Fact(kind=FactKind(kind), value=value, evidence=tuple(evidence))
        for (kind, value), evidence in sorted(grouped.items())
    )


def combine_results(results: Iterable[DetectorResult]) -> DetectorResult:
    items = list(results)
    return DetectorResult(
        exposes=merge_facts(f for r in items for f in r.exposes),
        consumes=merge_facts(f for r in items for f in r.consumes),
        aliases=tuple(dict.fromkeys(a for r in items for a in r.aliases)),
        stack=tuple(dict.fromkeys(s for r in items for s in r.stack)),
        commands=tuple(c for r in items for c in r.commands),
        layout=tuple(e for r in items for e in r.layout),
        readme_excerpt=next((r.readme_excerpt for r in items if r.readme_excerpt), None),
    )


def find_line(text: str, needle: str) -> tuple[int, str]:
    lines = text.splitlines()
    for number, line in enumerate(lines, start=1):
        if needle in line:
            return number, line
    return 1, lines[0] if lines else ""
