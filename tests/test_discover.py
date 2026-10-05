import subprocess
from pathlib import Path

from cairn.discover.git import GitInfo, git_info, normalize_remote
from cairn.discover.repos import discover_repos
from tests.helpers import make_repo, write


def _ids(ws: Path, **kwargs) -> list[str]:
    return [loc.id for loc in discover_repos(ws, **kwargs)]


def test_finds_repos_and_skips_noise(tmp_path: Path) -> None:
    make_repo(tmp_path, "app")
    make_repo(tmp_path, "group/service")
    make_repo(tmp_path, "app/vendored-sub")  # inside a repo: not descended into
    make_repo(tmp_path, "node_modules/pkg")
    make_repo(tmp_path, ".hidden/repo")
    write(tmp_path, "not-a-repo/readme.md", "x")
    assert _ids(tmp_path) == ["app", "service"]


def test_depth_limit(tmp_path: Path) -> None:
    make_repo(tmp_path, "a/b/c/d/e/deep")
    assert _ids(tmp_path, max_depth=4) == []
    assert _ids(tmp_path, max_depth=6) == ["deep"]


def test_duplicate_names_use_relative_path(tmp_path: Path) -> None:
    make_repo(tmp_path, "team-a/api")
    make_repo(tmp_path, "team-b/api")
    assert _ids(tmp_path) == ["team-a--api", "team-b--api"]


def test_ignore_repos(tmp_path: Path) -> None:
    make_repo(tmp_path, "keep")
    make_repo(tmp_path, "notes")
    assert _ids(tmp_path, ignore_repos=frozenset({"notes"})) == ["keep"]


def test_app_roots(tmp_path: Path) -> None:
    make_repo(tmp_path, "flat", {"package.json": "{}"})
    make_repo(tmp_path, "nested", {"my-app/package.json": "{}", "my-app/sub/package.json": "{}"})
    make_repo(tmp_path, "bare", {"notes.md": "x"})
    locs = {loc.id: loc for loc in discover_repos(tmp_path)}
    assert locs["flat"].app_roots == (locs["flat"].root,)
    assert [p.name for p in locs["nested"].app_roots] == ["my-app"]
    assert locs["bare"].app_roots == (locs["bare"].root,)
    assert locs["nested"].rel_path(tmp_path.resolve()) == "nested"


def test_normalize_remote_strips_credentials_and_suffix() -> None:
    assert (
        normalize_remote("https://bot:ghp_FAKE1234567890abcdef@github.com/acme/eats.git")
        == "github.com/acme/eats"
    )
    assert normalize_remote("git@github.com:acme/eats-admin.git") == "github.com/acme/eats-admin"
    assert normalize_remote("ssh://git@gitlab.com/acme/api") == "gitlab.com/acme/api"
    assert normalize_remote("/local/path/repo") is None


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.com",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def test_git_info_reads_real_repo(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "a.txt").write_text("a", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    _git(
        repo,
        "remote",
        "add",
        "origin",
        "https://bot:ghp_SECRETsecret1234567890@github.com/acme/r.git",
    )
    info = git_info(repo)
    assert info.head_sha and len(info.head_sha) >= 7
    assert info.remote == "github.com/acme/r"
    assert info.dirty is False
    (repo / "a.txt").write_text("changed", encoding="utf-8")
    assert git_info(repo).dirty is True


def test_git_info_survives_missing_git(tmp_path: Path, monkeypatch) -> None:
    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", no_git)
    assert git_info(tmp_path) == GitInfo()
