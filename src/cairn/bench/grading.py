"""Deterministic grading of benchmark answers (spec §11): file recall or required keywords."""

import re
from dataclasses import dataclass
from pathlib import Path

from cairn.bench.suite import Task

# Windows absolute, POSIX absolute, then relative `a/b/c` paths (either slash).
_PATH = re.compile(r"[A-Za-z]:[\\/][^\s`'\"()]+|/[^\s`'\"()]+|[\w@.\-]+(?:[\\/][\w@.\-]+)+")
_TRAILING = ".,;:)"
PASS_RECALL = 0.8


@dataclass(frozen=True)
class Grade:
    success: bool
    recall: float
    precision: float


def _is_absolute(path: str) -> bool:
    return path.startswith("/") or re.match(r"[A-Za-z]:/", path) is not None


def mentioned_files(text: str, ws_root: Path, working_repo: str, repo_ids: set[str]) -> set[str]:
    """Workspace paths (`repo/path`) named in `text`; bare paths are relative to the working repo."""
    root = ws_root.as_posix().rstrip("/") + "/"
    found: set[str] = set()
    for token in _PATH.findall(text):
        path = token.replace("\\", "/").rstrip(_TRAILING)
        if path.casefold().startswith(root.casefold()):
            path = path[len(root) :]
        elif _is_absolute(path):
            continue  # outside the workspace
        first = path.split("/", 1)[0]
        found.add(path if first in repo_ids else f"{working_repo}/{path}")
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
