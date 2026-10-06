"""Phase 5 Task 3: a warm refresh spawns fewer git processes and skips unchanged walks (§22)."""

import subprocess
from collections import Counter
from pathlib import Path

import pytest

import cairn.discover.files as files_module
import cairn.discover.proc as proc
from cairn.discover import git as git_module
from cairn.discover.git import GitInfo, git_info
from cairn.scan import scan_workspace
from cairn.scan_cache import repo_state, worktree_fingerprint


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def make_repo(ws: Path, name: str) -> Path:
    """A real git repo with one commit (tests.helpers.make_repo only fakes `.git/`)."""
    repo = ws / name
    repo.mkdir(parents=True)
    (repo / "README.md").write_text(f"# {name}\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "-m", "init")
    return repo


def _counted(monkeypatch: pytest.MonkeyPatch) -> Counter[str]:
    calls: Counter[str] = Counter()
    for name in ("run_text", "run_bytes"):
        real = getattr(proc, name)

        def counting(args, *a, _real=real, **kw):  # type: ignore[no-untyped-def]
            if args and args[0] == "git":
                calls["git"] += 1
            return _real(args, *a, **kw)

        monkeypatch.setattr(proc, name, counting)
        for module in (git_module, __import__("cairn.scan_cache", fromlist=["x"])):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, counting)
    return calls


@pytest.mark.parametrize("change", ["clean", "tracked", "untracked"])
def test_repo_state_matches_git_info_and_the_fingerprint(tmp_path: Path, change: str) -> None:
    repo = make_repo(tmp_path, "api")
    _git(repo, "remote", "add", "origin", "https://user:secret@github.com/acme/api.git")
    git_module.forget_git_memo()
    if change == "tracked":
        (repo / "README.md").write_text("changed\n", encoding="utf-8")
    elif change == "untracked":
        (repo / "new.txt").write_text("x\n", encoding="utf-8")
    info, fingerprint = repo_state(repo)
    assert info == git_info(repo)
    assert fingerprint == worktree_fingerprint(repo)
    assert info.remote == "github.com/acme/api"
    assert info.dirty is (change == "tracked")


def test_repo_state_spawns_three_git_processes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo(tmp_path, "api")
    git_module.forget_git_memo()
    calls = _counted(monkeypatch)
    repo_state(repo)
    assert calls["git"] == 3, calls  # config listing, rev-parse, status (was 5)


def test_local_filters_are_still_neutralised(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "api")
    _git(repo, "config", "filter.evil.clean", "touch PWNED")
    git_module.forget_git_memo()
    command = git_module.git_command(repo)
    assert "filter.evil.clean=" in command and "filter.evil.smudge=" in command


def test_a_warm_refresh_does_not_walk_unchanged_repos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("api", "web"):
        repo = make_repo(tmp_path, name)
        (repo / "docs").mkdir()
        (repo / "docs" / "notes.md").write_text("Calls the api service.\n", encoding="utf-8")
        (repo / "docker-compose.yml").write_text(
            "services:\n  app:\n    build: .\n    depends_on: [db]\n  db:\n    image: x\n",
            encoding="utf-8",
        )
        _git(repo, "add", "-A")
        _git(repo, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "-m", "more")
    first = scan_workspace(tmp_path)
    walks: Counter[str] = Counter()
    real = files_module.os.walk

    def counting(top, *args, **kwargs):  # type: ignore[no-untyped-def]
        walks[Path(top).name] += 1
        return real(top, *args, **kwargs)

    monkeypatch.setattr(files_module.os, "walk", counting)
    second = scan_workspace(tmp_path)
    assert set(second.cached) == {"api", "web"}
    assert not walks, walks
    assert second.workspace.edges == first.workspace.edges
    assert [r.contracts for r in second.workspace.repos] == [
        r.contracts for r in first.workspace.repos
    ]


def _forget() -> None:
    """A fresh process: nothing remembered in memory."""
    git_module.forget_git_memo()


def test_a_warm_refresh_runs_one_git_process_per_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("api", "web"):
        make_repo(tmp_path, name)
    scan_workspace(tmp_path)
    _forget()  # the next refresh is a new `cairn refresh` process: the memo comes from disk
    calls = _counted(monkeypatch)
    second = scan_workspace(tmp_path)
    assert set(second.cached) == {"api", "web"}
    assert calls["git"] == 2, calls  # one `git status` per repo


def test_the_memo_notices_commits_and_remote_changes(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "api")
    before, _ = repo_state(repo)
    (repo / "b.txt").write_text("b\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "-m", "two")
    _git(repo, "remote", "add", "origin", "https://github.com/acme/api.git")
    after, _ = repo_state(repo)
    assert after.head_sha and after.head_sha != before.head_sha
    assert after == git_info(repo) and after.remote == "github.com/acme/api"
    _git(repo, "checkout", "-q", "--detach")
    _git(
        repo,
        "-c",
        "user.email=a@b",
        "-c",
        "user.name=a",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "3",
    )
    assert repo_state(repo)[0].head_sha == git_info(repo).head_sha


def test_unusual_git_layouts_are_never_memoised(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "api")
    (repo / ".git" / "reftable").mkdir()
    assert git_module.head_stamp(repo) is None
    worktree = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", str(worktree))
    assert git_module.head_stamp(worktree) is None
    assert repo_state(worktree)[0].head_sha == git_info(worktree).head_sha


def test_git_info_is_unchanged_for_callers(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "api")
    info = git_info(repo)
    assert isinstance(info, GitInfo) and info.head_sha and info.dirty is False


def test_a_tampered_memo_cannot_configure_git(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "api")
    stamp = git_module.config_stamp(repo)
    _forget()
    git_module.import_git_memo(
        {
            str(repo): {
                "config": [stamp, ["-c", "filter.x.clean=touch PWNED"], None],
                "head": [git_module.head_stamp(repo), "not-a-sha; rm -rf"],
            }
        }
    )
    assert "filter.x.clean=touch PWNED" not in git_module.git_command(repo)
    assert git_module.head_sha(repo) == git_info(repo).head_sha
    assert git_module.head_sha(repo) != "not-a-sha; rm -rf"


def test_the_perf_script_runs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import importlib.util

    script = Path(__file__).resolve().parents[1] / "bench" / "perf_scan.py"
    spec = importlib.util.spec_from_file_location("perf_scan", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main(["--repos", "2", "--files", "3", "--out", str(tmp_path / "ws")]) == 0
    assert "cold scan" in capsys.readouterr().out
