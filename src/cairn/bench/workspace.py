"""Turn a checked-in fixture tree into a real workspace of git repos (tests and benchmarks)."""

import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

from cairn.discover.git import GIT

# cairn's hardened git (no hooks, no fsmonitor), plus a fixed identity for fixture commits.
CLONE_MARKER = ".fixture-clone-of"
_GIT = [*GIT, "-c", "user.name=cairn-bench", "-c", "user.email=bench@example.com"]
_GIT += ["-c", "commit.gpgsign=false", "-c", "core.symlinks=false"]


def _git(cwd: Path, *args: str) -> None:
    subprocess.run([*_GIT, *args], cwd=cwd, check=True, capture_output=True)


def materialize(
    source: Path,
    dest: Path,
    *,
    remotes: Mapping[str, str] | None = None,
    rename_dots: bool = True,
) -> Path:
    """Copy `source` to `dest`, turn `dot-x` names into `.x` (checked-in fixtures only: a
    fetched upstream tree is copied as is), and commit each `.fixture-repo` folder."""
    shutil.copytree(source, dest)
    if rename_dots:
        for path in sorted(dest.rglob("dot-*"), key=lambda p: len(p.parts), reverse=True):
            path.rename(path.with_name("." + path.name[len("dot-") :]))
    clones = []
    for marker in sorted(dest.rglob(".fixture-repo")):
        repo = marker.parent
        if (repo / CLONE_MARKER).is_file():
            clones.append(repo)  # needs its origin committed first
            continue
        marker.unlink()
        _git(repo, "init", "-q")
        _git(repo, "add", "-A")
        # A message per repo: identical fixture trees committed in the same second would
        # otherwise share a root commit and look like copies of one app.
        _git(repo, "commit", "-q", "-m", f"fixture {repo.name}")
        _set_remote(repo, remotes)
    for repo in clones:
        _clone_overlay(repo)
        _set_remote(repo, remotes)
    return dest


def _clone_overlay(repo: Path) -> None:
    """`.fixture-clone-of` names a sibling: clone it (shared history), then commit this
    folder's own files on top, as a per-event copy of an app would be."""
    origin = repo.parent / (repo / CLONE_MARKER).read_text(encoding="utf-8").strip()
    (repo / CLONE_MARKER).unlink()
    (repo / ".fixture-repo").unlink()
    staging = repo.with_name(f"{repo.name}.clone")
    _git(repo.parent, "clone", "-q", str(origin), str(staging))
    _git(staging, "remote", "remove", "origin")
    shutil.copytree(repo, staging, dirs_exist_ok=True)
    shutil.rmtree(repo)
    staging.rename(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", f"fixture {repo.name}")


def _set_remote(repo: Path, remotes: Mapping[str, str] | None) -> None:
    if remotes and repo.name in remotes:
        _git(repo, "remote", "add", "origin", remotes[repo.name])
