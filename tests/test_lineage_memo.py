"""0.7.2: a repo's first commits are remembered per HEAD, and a timeout is reported, not
silently read as "no copies" (it dropped two copy links on a real workspace)."""

import subprocess
from pathlib import Path

import pytest

from cairn.discover import git as git_module
from cairn.discover.proc import Capped
from cairn.scan import scan_workspace


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _repo(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "README.md").write_text("# app\n", encoding="utf-8")
    _git(path, "init", "-q")
    _git(path, "add", "-A")
    _git(path, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "-m", path.name)
    return path


def _copies(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    _repo(ws / "app")
    _git(ws, "clone", "-q", str(ws / "app"), "app-2026")
    return ws


def _count_rev_lists(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    real = git_module.run_bytes_capped

    def counting(command, **kwargs):  # type: ignore[no-untyped-def]
        if "rev-list" in command:
            calls.append(1)
        return real(command, **kwargs)

    monkeypatch.setattr(git_module, "run_bytes_capped", counting)
    return calls


def test_first_commits_are_remembered_per_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path / "app")
    git_module.forget_git_memo()
    calls = _count_rev_lists(monkeypatch)
    first = git_module.root_commits(repo)
    assert first and len(first[0]) == 40
    assert git_module.root_commits(repo) == first and len(calls) == 1
    # ...across processes too: the memo file carries them.
    saved = git_module.export_git_memo([repo])
    git_module.forget_git_memo()
    git_module.import_git_memo(saved)
    assert git_module.root_commits(repo) == first and len(calls) == 1


def test_a_new_commit_asks_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path / "app")
    git_module.forget_git_memo()
    calls = _count_rev_lists(monkeypatch)
    git_module.root_commits(repo)
    (repo / "b.txt").write_text("b\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "-m", "b")
    git_module.root_commits(repo)
    assert len(calls) == 2


def test_a_malformed_memo_entry_is_ignored() -> None:
    git_module.forget_git_memo()
    git_module.import_git_memo({"/r": {"roots": ["stamp", ["not-a-sha", 5]]}})
    git_module.import_git_memo({"/r": {"roots": "nonsense"}})
    assert git_module.export_git_memo([Path("/r")]) == {}


def test_a_timeout_is_reported_and_never_cached_as_no_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _copies(tmp_path)
    git_module.forget_git_memo()
    real = git_module.run_bytes_capped

    def slow_rev_list(command, **kwargs):  # type: ignore[no-untyped-def]
        if "rev-list" in command:
            return Capped(None, b"", False, True)
        return real(command, **kwargs)

    monkeypatch.setattr(git_module, "run_bytes_capped", slow_rev_list)
    result = scan_workspace(ws)
    warning = next(w for w in result.warnings if "first commit" in w)
    assert "app" in warning and "app-2026" in warning
    monkeypatch.setattr(git_module, "run_bytes_capped", real)
    copies = [e for e in scan_workspace(ws).workspace.edges if e.type.value == "mirrors"]
    assert copies  # the next scan reads them: the failure wasn't cached as "no roots"
