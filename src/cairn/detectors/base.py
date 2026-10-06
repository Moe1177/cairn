"""Shared detector types and helpers."""

import re
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from cairn.config import CairnConfig
from cairn.discover.files import DEFAULT_IGNORE_DIRS, crosses_link, read_text, walk_groups
from cairn.discover.repos import RepoLocation
from cairn.model.graph import (
    MAX_EVIDENCE,
    Command,
    Evidence,
    Fact,
    FactKind,
    LayoutEntry,
    Package,
)
from cairn.security.redact import make_snippet

# Text kept per context so detectors share one read of each file; bounded so a huge repo
# never sits in memory (8 scan workers -> at most 8x this).
READ_CACHE_BYTES = 16 * 1024 * 1024

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

_SQL_DATA = re.compile(r"(?i)\b(?:insert\s+into|values|copy)\b")


class _RepoFiles:
    """One walk and one read per file, shared by every detector using the same context."""

    def __init__(self) -> None:
        # Folder -> file names: one Path per folder, not per file (a 500k-file monorepo
        # would otherwise hold ~0.5 GB of Path objects per worker).
        self.groups: tuple[tuple[Path, tuple[str, ...]], ...] | None = None
        self.dirs: frozenset[Path] = frozenset()
        self.text: dict[Path, str | None] = {}
        self.bytes = 0


@dataclass(frozen=True)
class KnownFiles:
    """Files a cached scan already found for these filters: a walk-free index."""

    matchers: tuple[Callable[[str], bool], ...]
    paths: tuple[Path, ...]


@dataclass(frozen=True)
class DetectorContext:
    """One repo, one scan phase. Files are walked and read once, so a context is a snapshot:
    take a new one to see later changes."""

    workspace_root: Path
    repo: RepoLocation
    config: CairnConfig
    alias_table: Mapping[str, str] = field(default_factory=dict)
    known_files: KnownFiles | None = None
    _files: _RepoFiles = field(default_factory=_RepoFiles, init=False, repr=False, compare=False)

    def rel(self, path: Path) -> str:
        return path.relative_to(self.repo.root).as_posix()

    def evidence(self, path: Path, line_no: int, line: str) -> Evidence:
        # Seed/fixture rows in .sql files are data: keep where, never what (spec §20.1).
        seed = path.suffix.lower() == ".sql" and _SQL_DATA.search(line) is not None
        snippet = "" if seed else make_snippet(line)
        return Evidence(repo=self.repo.id, file=self.rel(path), line=line_no, snippet=snippet)

    def files(self, match: Callable[[str], bool]) -> Iterator[Path]:
        """The repo's files whose name `match`es, in walk order. The repo is walked once."""
        cache = self._files
        known = self.known_files
        if cache.groups is None and known is not None and match in known.matchers:
            return (path for path in known.paths if match(path.name))
        groups = self._groups()
        return (folder / name for folder, names in groups for name in names if match(name))

    def _groups(self) -> tuple[tuple[Path, tuple[str, ...]], ...]:
        cache = self._files
        if cache.groups is None:
            ignore = DEFAULT_IGNORE_DIRS | NOISE_DIRS | frozenset(self.config.ignore_dirs)
            cache.groups = tuple(
                (folder, tuple(names))
                for folder, names in walk_groups(
                    self.repo.root,
                    ignore_dirs=ignore,
                    max_bytes=self.config.max_file_bytes,
                    match=lambda name: not _TEST_FILE.search(name),
                )
            )
            cache.dirs = frozenset(folder for folder, _ in cache.groups)
        return cache.groups

    def folder_stamps(self) -> tuple[tuple[str, int], ...]:
        """(repo-relative folder, mtime) for every walked folder: a file created or deleted in
        one changes its mtime, so a cached file list can be checked without walking."""
        stamps = []
        for folder, _ in self._groups():
            try:
                mtime = folder.stat().st_mtime_ns
            except OSError:
                mtime = -1
            stamps.append((folder.relative_to(self.repo.root).as_posix(), mtime))
        return tuple(stamps)

    def read(self, path: Path) -> str | None:
        cache = self._files
        if path in cache.text:
            return cache.text[path]
        # The walk never enters links, so a file in a walked folder needs no per-component check.
        if path.parent not in cache.dirs:
            try:
                if crosses_link(self.repo.root, path):
                    return None  # e.g. `supabase/.temp` -> a folder outside the repo
            except ValueError:
                pass  # not below this repo (a sibling path ref); read_text still refuses links
        text = read_text(path, self.config.max_file_bytes)
        size = sys.getsizeof(text) if text is not None else 0  # memory, not characters
        if cache.bytes + size <= READ_CACHE_BYTES:
            cache.text[path] = text
            cache.bytes += size
        return text

    def matching(self, matchers: Iterable[Callable[[str], bool]]) -> tuple[Path, ...]:
        """Every file any of `matchers` would select (one walk), for the scan cache."""
        tests = tuple(matchers)
        return tuple(p for p in self.files(lambda _: True) if any(t(p.name) for t in tests))

    def cached_bytes(self) -> int:
        return self._files.bytes


@dataclass(frozen=True)
class DetectorResult:
    exposes: tuple[Fact, ...] = ()
    consumes: tuple[Fact, ...] = ()
    aliases: tuple[str, ...] = ()
    stack: tuple[str, ...] = ()
    commands: tuple[Command, ...] = ()
    layout: tuple[LayoutEntry, ...] = ()
    readme_excerpt: str | None = None
    packages: tuple[Package, ...] = ()


class Detector(Protocol):
    id: str

    def run(self, ctx: DetectorContext) -> DetectorResult: ...


def merge_facts(facts: Iterable[Fact]) -> tuple[Fact, ...]:
    grouped: dict[tuple[str, str], list[Evidence]] = {}
    hints: dict[tuple[str, str], list[str]] = {}
    for fact in facts:
        key = (fact.kind.value, fact.value)
        bucket = grouped.setdefault(key, [])
        for ev in fact.evidence:
            if ev not in bucket and len(bucket) < MAX_EVIDENCE:
                bucket.append(ev)
        known = hints.setdefault(key, [])
        known += [h for h in fact.hints if h not in known][: _MAX_HINTS - len(known)]
    return tuple(
        Fact(
            kind=FactKind(kind),
            value=value,
            evidence=tuple(evidence),
            hints=tuple(hints[(kind, value)]),
        )
        for (kind, value), evidence in sorted(grouped.items())
    )


_MAX_HINTS = 5


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
        packages=tuple({p.path: p for r in items for p in r.packages}.values()),
    )


def find_line(text: str, needle: str) -> tuple[int, str]:
    lines = text.splitlines()
    for number, line in enumerate(lines, start=1):
        if needle in line:
            return number, line
    return 1, lines[0] if lines else ""
