"""Deterministic grading of benchmark answers (spec §11): file recall or required keywords."""

import posixpath
import re
from dataclasses import dataclass
from pathlib import Path

from cairn.bench.suite import Task

_SEGMENT = r"[\w@.\-\[\]]+"
# Windows absolute, POSIX absolute, then relative `a/b/c` paths (either slash).
_PATH = re.compile(rf"[A-Za-z]:[\\/][^\s`'\"()]+|/[^\s`'\"()]+|{_SEGMENT}(?:[\\/]{_SEGMENT})+")
_TRAILING = ".,;:)"
_DRIVE = re.compile(r"([A-Za-z]):/(.*)")
_MSYS = re.compile(r"/([A-Za-z])/(.*)")
PASS_RECALL = 0.8


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


def mentioned_files(text: str, ws_root: Path, working_repo: str, repo_ids: set[str]) -> set[str]:
    """Workspace paths (`repo/path`) named in `text`.

    A bare path belongs to the repo named by the heading it sits under (`**orders-svc:**`),
    else to the working repo.
    """
    roots = _root_spellings(ws_root)
    ws_parts = tuple(p for p in ws_root.as_posix().split("/") if p)
    found: set[str] = set()
    context = working_repo
    for line in text.splitlines():
        heading = _heading_repo(line, repo_ids)
        if heading is not False:
            context = heading or working_repo
            continue
        for token in _PATH.findall(line):
            path = token.replace("\\", "/").rstrip(_TRAILING)
            if path.startswith("/") or _DRIVE.match(path):
                inside = _inside(path, roots)
                if inside is None:
                    continue
                path = inside
            else:
                path = _strip_root_tail(path, ws_parts, repo_ids)
                if path.split("/", 1)[0] not in repo_ids:
                    path = f"{context}/{path}"
            path = posixpath.normpath(path)
            if not path.startswith(".."):
                found.add(path)
    return found


def grade(task: Task, text: str, ws_root: Path, repo_ids: set[str]) -> Grade:
    keywords_ok = all(k.lower() in text.lower() for k in task.expect_keywords)
    if not task.expect_files:
        return Grade(success=keywords_ok, recall=1.0 if keywords_ok else 0.0, precision=1.0)
    found = mentioned_files(text, ws_root, task.repo, repo_ids)
    expected = set(task.expect_files)
    hits = len(found & expected)
    recall = hits / len(expected)
    precision = hits / len(found) if found else 0.0
    return Grade(success=keywords_ok and recall >= PASS_RECALL, recall=recall, precision=precision)
