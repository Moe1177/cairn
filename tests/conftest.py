"""Shared fixtures: materialize fixture workspaces as real git repos."""

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "workspaces"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=cairn-test", "-c", "user.email=test@example.com",
         "-c", "commit.gpgsign=false", *args],
        cwd=cwd, check=True, capture_output=True,
    )


@pytest.fixture
def materialize(tmp_path: Path) -> Callable[..., Path]:
    def _make(name: str, remotes: dict[str, str] | None = None) -> Path:
        dest = tmp_path / name
        shutil.copytree(FIXTURES / name, dest)
        for path in sorted(dest.rglob("dot-*"), key=lambda p: len(p.parts), reverse=True):
            path.rename(path.with_name("." + path.name[len("dot-"):]))
        for marker in sorted(dest.rglob(".fixture-repo")):
            repo = marker.parent
            marker.unlink()
            _git(repo, "init", "-q")
            _git(repo, "add", "-A")
            _git(repo, "commit", "-q", "-m", "fixture")
            if remotes and repo.name in remotes:
                _git(repo, "remote", "add", "origin", remotes[repo.name])
        return dest

    return _make
