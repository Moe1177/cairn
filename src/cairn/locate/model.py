"""What every locator returns: places in a repo, each saying why and who found it."""

from dataclasses import dataclass


@dataclass(frozen=True)
class LocateHit:
    file: str  # repo-relative, POSIX
    line: int | None
    why: str
    source: str  # "grep", "graph" or "grep+graph"
    symbol: str | None = None
    score: float = 0.0
    repo: str | None = None
    defines: bool = False  # the line defines a searched term (`def X`, `const X =`)
    also: tuple[str, ...] = ()  # copies of this repo with the same place (same file and line)


@dataclass(frozen=True)
class GrepResult:
    hits: tuple[LocateHit, ...]
    files_matched: int
    truncated: bool  # more files matched than were kept
    partial: bool = False  # the search stopped early (time or size limit): some files unseen


@dataclass(frozen=True)
class LocateResult:
    hits: tuple[LocateHit, ...]
    route: str  # which locator answered: "grep", "graph" or "grep+graph"
    reason: str  # why that locator, in a few words
    truncated: bool = False
    partial: bool = False  # a search stopped early
