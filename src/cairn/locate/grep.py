"""Exact-text locator: find the question's own words in a repo, definitions first.

`git grep -F` (fixed strings: a term is never a pattern) through cairn's hardened git, over
tracked and untracked files, skipping binaries, lockfiles, minified and generated output. Where
git can't run, the same search walks the files in Python.
"""

import os
import re
import time
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import pathspec

from cairn.discover.files import iter_files, read_text
from cairn.discover.git import git_command, git_env
from cairn.discover.proc import run_bytes, run_bytes_capped
from cairn.locate.model import GrepResult, LocateHit
from cairn.security.policy import is_forbidden, never_open_globs

GREP_TIMEOUT = 10.0
GREP_MAX_BYTES = 2_000_000  # git grep output kept; past that the search stops (partial)
MAX_LINE = 400  # longer lines are minified or generated: never a place to read
_LINES_PER_FILE = 50
_FALLBACK_FILES = 20_000
_FALLBACK_SECONDS = 5.0
NOISE = (
    "**/package-lock.json",
    "**/npm-shrinkwrap.json",
    "**/yarn.lock",
    "**/pnpm-lock.yaml",
    "**/*.lock",
    "**/go.sum",
    "**/*.min.js",
    "**/*.min.css",
    "**/*.map",
    "**/*.snap",
    "**/*.svg",
    "**/__snapshots__/**",
    "**/node_modules/**",
    "**/dist/**",
    "**/build/**",
    "**/vendor/**",
    "**/.next/**",
    "**/coverage/**",
)
_NOISE_SPEC = pathspec.GitIgnoreSpec.from_lines(NOISE)
_LOW_VALUE = re.compile(
    r"(?:^|/)(?:tests?|__tests__|spec|specs|fixtures?|examples?|docs?|e2e|mocks?)/"
    r"|\.(?:test|spec)\.[a-z]+$|(?:^|/)test_[^/]+$|_test\.[a-z]+$|\.md$",
    re.IGNORECASE,
)
_DEF_KEYWORDS = (
    r"def|function|func|fn|class|interface|type|struct|enum|trait|module|const|let|var|val"
)
_ROUTE_CONTEXT = re.compile(r"\b(?:get|post|put|patch|delete|route|path|router|app|api)\b", re.I)
_NAME_CHARS = re.compile(r"[^a-z0-9]")


@dataclass
class _FileMatch:
    lines: list[tuple[int, str]] = field(default_factory=list)
    count: int = 0


def grep_locate(
    repo_root: Path,
    terms: Sequence[str],
    *,
    limit: int = 10,
    names: bool = True,
    label_definitions: bool = True,
) -> GrepResult:
    """The files holding `terms`, best first: one hit per file, at its most telling line.
    `label_definitions=False` for plain words: `const applications = ...` defines a variable,
    not what the question asked about, so the hit isn't called a definition."""
    terms = tuple(t for t in terms if t.strip())
    if not terms:
        return GrepResult((), 0, False)
    wants_names = names and any(len(_name_key(t)) >= 3 for t in terms)
    with ThreadPoolExecutor(max_workers=1) as pool:
        # The file listing doesn't depend on the search: list while git greps.
        listing = pool.submit(lambda: list(_list_files(repo_root))) if wants_names else None
        searched = _git_grep(repo_root, terms)
        if searched is None:  # git can't search here at all (not a timeout): read the files
            searched = _python_grep(repo_root, terms)
        matches, partial = searched
        scored = [
            _score_file(rel, found, terms, label=label_definitions)
            for rel, found in matches.items()
        ]
        if listing is not None:
            scored = _with_name_hits(listing.result(), scored, terms)
    scored.sort(key=lambda hit: (-hit.score, hit.file))
    return GrepResult(tuple(scored[:limit]), len(scored), len(scored) > limit, partial)


def _git_grep(root: Path, terms: Sequence[str]) -> tuple[dict[str, _FileMatch], bool] | None:
    """(matches, partial), or None when git can't search this folder (not a repo, no git)."""
    patterns = [arg for term in terms for arg in ("-e", term)]
    # Secret files are excluded so git never opens them (spec §20.1), not just filtered after.
    excludes = [f":(exclude,glob){pattern}" for pattern in NOISE]
    excludes += [f":(exclude,glob,icase){pattern}" for pattern in never_open_globs()]
    command = [
        *git_command(root),
        "-c",
        "core.quotePath=false",
        "grep",
        "-n",
        "-I",
        "-F",
        "-i",
        "-z",
        "--no-color",
        "--untracked",
        *patterns,
        "--",
        ".",
        *excludes,
    ]
    done = run_bytes_capped(
        command, cwd=root, timeout=GREP_TIMEOUT, env=git_env(), max_bytes=GREP_MAX_BYTES
    )
    if done is None:
        return None
    partial = done.capped or done.timed_out
    if not partial and done.returncode not in (0, 1):
        return None  # not a repo, or git refused it: search the files directly
    found: dict[str, _FileMatch] = {}
    for record in done.stdout.split(b"\n"):
        parts = record.split(b"\0", 2)
        if len(parts) != 3 or not parts[1].isdigit():
            continue
        rel = os.fsdecode(parts[0]).replace("\\", "/")
        _record(found, rel, int(parts[1]), parts[2].decode("utf-8", "replace"))
    return found, partial


def _python_grep(root: Path, terms: Sequence[str]) -> tuple[dict[str, _FileMatch], bool]:
    lowered = [t.lower() for t in terms]
    found: dict[str, _FileMatch] = {}
    deadline = time.monotonic() + _FALLBACK_SECONDS
    for count, path in enumerate(iter_files(root)):
        if count >= _FALLBACK_FILES or time.monotonic() > deadline:
            return found, True  # stopped early: say so
        rel = path.relative_to(root).as_posix()
        if _NOISE_SPEC.match_file(rel):
            continue
        text = read_text(path)
        if text is None or not any(t in text.lower() for t in lowered):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if any(t in line.lower() for t in lowered):
                _record(found, rel, number, line)
    return found, False


def _record(found: dict[str, _FileMatch], rel: str, number: int, line: str) -> None:
    if len(line) > MAX_LINE or is_forbidden(Path(rel)):
        return
    match = found.setdefault(rel, _FileMatch())
    match.count += 1
    if len(match.lines) < _LINES_PER_FILE:
        match.lines.append((number, line))


def _score_file(rel: str, found: _FileMatch, terms: Sequence[str], *, label: bool) -> LocateHit:
    best: tuple[float, int, list[str], bool] = (-1.0, 0, [], False)
    seen: set[str] = set()
    for number, line in found.lines:
        present = [t for t in terms if t.lower() in line.lower()]
        seen.update(present)
        definition = any(_defines(line, t) for t in present)
        exact = any(t in line for t in present)
        score = len(present) + (0.2 if exact else 0.0) + (2.0 if definition else 0.0)
        if score > best[0]:
            best = (score, number, present, definition)
    score = best[0] + 0.1 * min(found.count - 1, 10) + len(seen) / len(terms)
    if _LOW_VALUE.search(rel):
        score *= 0.5
    why = f"grep: {', '.join(best[2])}" + (" (definition)" if best[3] and label else "")
    return LocateHit(
        file=rel, line=best[1], why=why, source="grep", score=round(score, 3), defines=best[3]
    )


def _defines(line: str, term: str) -> bool:
    """Does `line` define `term` (or, for a route, declare it)?"""
    if term.startswith("/"):
        return bool(_ROUTE_CONTEXT.search(line))
    name = re.escape(term)
    return bool(
        re.search(rf"\b(?:{_DEF_KEYWORDS})\s+\*?\s*{name}\b", line, re.IGNORECASE)
        or re.search(rf"(?:^|\s|\.){name}\s*[:=]\s*(?:function|async|class|\(|\w+\s*=>)", line)
    )


def _with_name_hits(
    files: Iterable[str], scored: list[LocateHit], terms: Sequence[str]
) -> list[LocateHit]:
    """Boost (or add) files whose name is a term: `charge.py`, `OrderService` -> OrderService.ts
    or order_service.py."""
    wanted = {_name_key(t): t for t in terms if len(_name_key(t)) >= 3}
    if not wanted:
        return scored
    by_file = {hit.file: hit for hit in scored}
    for rel in files:
        name = PurePosixPath(rel).name
        term = wanted.get(_name_key(name)) or wanted.get(_name_key(PurePosixPath(rel).stem))
        if term is None or _NOISE_SPEC.match_file(rel) or is_forbidden(Path(rel)):
            continue
        bonus = 3.0 * (0.5 if _LOW_VALUE.search(rel) else 1.0)
        hit = by_file.get(rel)
        if hit is None:
            by_file[rel] = LocateHit(
                file=rel, line=None, why=f"file name: {term}", source="grep", score=bonus
            )
        else:
            by_file[rel] = LocateHit(
                file=rel,
                line=hit.line,
                why=f"{hit.why}; file name: {term}",
                source="grep",
                score=round(hit.score + bonus, 3),
                defines=hit.defines,
            )
    return list(by_file.values())


def _name_key(text: str) -> str:
    return _NAME_CHARS.sub("", text.lower())


def _list_files(root: Path) -> Iterable[str]:
    command = [*git_command(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
    done = run_bytes(command, cwd=root, timeout=GREP_TIMEOUT, env=git_env())
    if done is not None and done[0] == 0:
        return [os.fsdecode(p) for p in done[1].split(b"\0") if p]
    return [p.relative_to(root).as_posix() for p in iter_files(root)]
