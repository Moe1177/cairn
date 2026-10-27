"""Deterministic grading of benchmark answers (spec §11): file recall or required keywords."""

import os
import posixpath
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from cairn.bench.suite import Task
from cairn.config import OrgSource

_SEGMENT = r"[\w@.\-\[\]]+"
# Windows absolute, POSIX absolute, then relative `a/b/c` paths (either slash).
_PATH = re.compile(rf"[A-Za-z]:[\\/][^\s`'\"()]+|/[^\s`'\"()]+|{_SEGMENT}(?:[\\/]{_SEGMENT})+")
_TRAILING = ".,;:)"
_DRIVE = re.compile(r"([A-Za-z]):/(.*)")
_MSYS = re.compile(r"/([A-Za-z])/(.*)")
PASS_RECALL = 0.8
_LINE = re.compile(r"(?::\d+){1,2}$|#L\d+(?:-L?\d+)?$")
_SKIP_DIRS = frozenset({".git", ".cairn", "node_modules"})
_CELL_TRIM = " `*_"


@dataclass(frozen=True)
class Grade:
    success: bool
    recall: float
    precision: float


def _root_spellings(ws_root: Path) -> tuple[str, ...]:
    """The workspace root as an agent might print it: as given, resolved, Git Bash style."""
    spellings: set[str] = set()
    for root in {ws_root.as_posix(), ws_root.resolve().as_posix()}:
        root = root.rstrip("/") + "/"
        spellings.add(root)
        drive = _DRIVE.fullmatch(root)
        if drive:
            spellings.add(f"/{drive.group(1).lower()}/{drive.group(2)}")
    return tuple(sorted(spellings, key=len, reverse=True))


def _inside(path: str, roots: tuple[str, ...]) -> str | None:
    """`path` relative to the workspace, or None when it points elsewhere."""
    for root in roots:
        if path.casefold().startswith(root.casefold()):
            return path[len(root) :]
    windows = any(_DRIVE.match(root) for root in roots)
    try:  # 8.3 short names, symlinked temp dirs (macOS /var -> /private/var)
        msys = _MSYS.fullmatch(path) if windows else None
        real = Path(f"{msys.group(1)}:/{msys.group(2)}" if msys else path)
        resolved = real.resolve().as_posix()
    except (OSError, ValueError):
        return None
    for root in roots:
        if resolved.casefold().startswith(root.casefold()):
            return resolved[len(root) :]
    return None


def _heading_repo(line: str, repo_ids: set[str]) -> str | None | bool:
    """For a heading-like line with no paths: the one repo it names, or None.

    Returns False when the line isn't a heading (the current context carries on).
    """
    stripped = line.strip().strip("-* ").strip()
    heading = line.lstrip().startswith("#") or stripped.endswith(":") or line.strip().endswith("**")
    if not stripped or not heading or _PATH.search(line):
        return False
    named = [r for r in repo_ids if re.search(rf"(?<![\w-]){re.escape(r)}(?![\w-])", line)]
    return named[0] if len(named) == 1 else None


def _strip_root_tail(path: str, ws_parts: tuple[str, ...], repo_ids: set[str]) -> str:
    """`ws/orders-svc/x` (relative to the workspace's parent) -> `orders-svc/x`."""
    segments = path.split("/")
    for i in range(1, min(len(segments), len(ws_parts) + 1)):
        if segments[i] in repo_ids and tuple(segments[:i]) == ws_parts[-i:]:
            return "/".join(segments[i:])
    return path


@lru_cache(maxsize=8)
def _by_suffix(ws_root: str) -> dict[str, tuple[str, ...]]:
    """Every workspace file (`repo/path`) under each of its trailing paths of two or more parts:
    `handlers/x.ts` -> (`stubs/queue/handlers/x.ts`, ...)."""
    index: dict[str, list[str]] = {}
    for current, dirnames, filenames in os.walk(ws_root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        rel_dir = Path(current).relative_to(ws_root).as_posix()
        if rel_dir == ".":
            continue
        for name in filenames:
            parts = f"{rel_dir}/{name}".split("/")
            for start in range(1, len(parts) - 1):
                index.setdefault("/".join(parts[start:]), []).append("/".join(parts))
    return {suffix: tuple(files) for suffix, files in index.items()}


def _resolve(path: str, context: str, ws_root: Path) -> str:
    """A bare path in `context`, or else the one workspace file it ends: an answer that writes
    `handlers/x.ts` under "all in `stubs/queue/`" names that file if no other ends that way."""
    candidate = f"{context}/{path}"
    if (ws_root / candidate).is_file():
        return candidate
    matches = _by_suffix(str(ws_root)).get(path.strip("/"), ()) if ws_root.is_dir() else ()
    return matches[0] if len(matches) == 1 else candidate


def _row_repo(line: str, repo_ids: set[str]) -> str | None:
    """The repo a table row names in a cell of its own: `| orders-svc | app/main.py |`."""
    if not line.lstrip().startswith("|"):
        return None
    cells = {c.strip(_CELL_TRIM) for c in line.strip().strip("|").split("|")}
    named = cells & repo_ids
    return next(iter(named)) if len(named) == 1 else None


def mentioned_files(text: str, ws_root: Path, working_repo: str, repo_ids: set[str]) -> set[str]:
    """Workspace paths (`repo/path`) named in `text`.

    A bare path belongs to the repo its table row names, else to the repo named by the heading
    it sits under (`**orders-svc:**`), else to the working repo; failing that, to the one
    workspace file it is the end of.
    """
    roots = _root_spellings(ws_root)
    ws_parts = tuple(p for p in ws_root.as_posix().split("/") if p)
    found: set[str] = set()
    context = working_repo
    for line in text.splitlines():
        heading = _heading_repo(line, repo_ids)
        if heading is not False:
            context = heading if isinstance(heading, str) else working_repo
            continue
        row = _row_repo(line, repo_ids) or context
        for token in _PATH.findall(line):
            # `lib/cart.ts:7`, `lib/cart.ts:7:3`, `lib/cart.ts#L7`: the file, not a line in it.
            path = _LINE.sub("", token.replace("\\", "/").rstrip(_TRAILING)).rstrip(_TRAILING)
            if path.startswith("/") or _DRIVE.match(path):
                inside = _inside(path, roots)
                if inside is None:
                    continue
                path = inside
            else:
                path = _strip_root_tail(path, ws_parts, repo_ids)
                if path.split("/", 1)[0] not in repo_ids:
                    path = _resolve(path, row, ws_root)
            path = posixpath.normpath(path)
            if not path.startswith(".."):
                found.add(path)
    return found


_REST = r"([^\s`'\"()|<>,;]+)"


def org_paths(text: str, org: OrgSource, ws_root: Path, repo_ids: set[str]) -> str:
    """An org repo's file as the org tools print it (`openfaas/faas/x.go`), or a link to it
    (`https://github.com/openfaas/faas/blob/main/x.go`, a raw.githubusercontent.com one), as
    the workspace path `faas/x.go`. Only when the workspace has that file: a folder that merely
    shares the org's name (`chart/openfaas/templates/x.yaml`) keeps its own path."""
    canonical = {repo.lower(): repo for repo in repo_ids}
    host, owner = re.escape(org.host), re.escape(org.org)

    def in_workspace(repo: str, rest: str) -> str | None:
        name = canonical.get(repo.lower())
        path = _LINE.sub("", rest.rstrip(_TRAILING)).rstrip(_TRAILING)
        return f"{name}/{rest}" if name and (ws_root / name / path).is_file() else None

    def link(match: re.Match[str]) -> str:
        repo, parts = match.group(1) or match.group(2), match.group(3).split("/")
        for cut in range(1, len(parts)):  # a branch name may hold slashes: try each split
            found = in_workspace(repo, "/".join(parts[cut:]))
            if found:
                return found
        return match.group(0)

    links = re.compile(
        rf"(?i)(?:https?://)?(?:{host}/{owner}/([\w.-]+)/(?:-/)?(?:blob|tree|raw)/"
        rf"|raw\.githubusercontent\.com/{owner}/([\w.-]+)/){_REST}"
    )
    text = links.sub(link, text)
    plain = re.compile(rf"(?i)(?<![\w./-])(?:{host}/)?{owner}/([\w.-]+)/{_REST}")
    return plain.sub(lambda m: in_workspace(m.group(1), m.group(2)) or m.group(0), text)


def grade(
    task: Task, text: str, ws_root: Path, repo_ids: set[str], org: OrgSource | None = None
) -> Grade:
    """`org`: the suite's org, when the agent read the other repos through it (--scope repo)."""
    if org is not None:
        text = org_paths(text, org, ws_root, repo_ids)
    keywords_ok = all(k.lower() in text.lower() for k in task.expect_keywords)
    if not task.expect_files:
        return Grade(success=keywords_ok, recall=1.0 if keywords_ok else 0.0, precision=1.0)
    found = mentioned_files(text, ws_root, task.repo, repo_ids)
    expected = set(task.expect_files)
    hits = len(found & expected)
    recall = hits / len(expected)
    precision = hits / len(found) if found else 0.0
    return Grade(success=keywords_ok and recall >= PASS_RECALL, recall=recall, precision=precision)
