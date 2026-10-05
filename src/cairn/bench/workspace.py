"""Turn a checked-in fixture tree into a real workspace of git repos (tests and benchmarks)."""

import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

_GIT = ["git", "-c", "user.name=cairn-bench", "-c", "user.email=bench@example.com"]
_GIT += ["-c", "commit.gpgsign=false"]


def _git(cwd: Path, *args: str) -> None:
    subprocess.run([*_GIT, *args], cwd=cwd, check=True, capture_output=True)


def materialize(source: Path, dest: Path, *, remotes: Mapping[str, str] | None = None) -> Path:
    """Copy `source` to `dest`, turn `dot-x` names into `.x`, and commit each `.fixture-repo` folder."""
    shutil.copytree(source, dest)
    for path in sorted(dest.rglob("dot-*"), key=lambda p: len(p.parts), reverse=True):
        path.rename(path.with_name("." + path.name[len("dot-") :]))
    for marker in sorted(dest.rglob(".fixture-repo")):
        repo = marker.parent
        marker.unlink()
        _git(repo, "init", "-q")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "fixture")
        if remotes and repo.name in remotes:
            _git(repo, "remote", "add", "origin", remotes[repo.name])
    return dest
