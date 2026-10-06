"""Phase 5 final-review fixes: the git memo, warm live files, --full, memory, CI and tools."""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

import cairn.detectors.base as base_module
from cairn.cli import app
from cairn.config import CairnConfig
from cairn.discover import git as git_module
from cairn.discover.git import git_info
from cairn.discover.repos import RepoLocation
from cairn.paths import repo_cache_dir
from cairn.scan import scan_workspace
from cairn.scan_cache import repo_state
from tests.test_warm_refresh import _git, make_repo

ROOT = Path(__file__).resolve().parents[1]


def _memo_path(ws: Path) -> Path:
    return repo_cache_dir(ws).parent / "git-memo.json"


def _hostile_filter(repo: Path, tmp_path: Path) -> Path:
    """A repo whose own config runs a program on `git status`; returns the marker it writes."""
    marker = tmp_path / "MARK"
    script = tmp_path / "evil.py"
    script.write_text(
        f"import sys\nopen(r'{marker}', 'a').write('x')\n"
        "sys.stdout.buffer.write(sys.stdin.buffer.read())\n",
        encoding="utf-8",
    )
    (repo / ".gitattributes").write_text("* filter=evil\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "-m", "attrs")
    command = f'"{Path(sys.executable).as_posix()}" "{script.as_posix()}"'
    _git(repo, "config", "filter.evil.clean", command)
    return marker


def test_a_tampered_memo_can_never_switch_filter_neutralisation_off(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    repo = make_repo(ws, "app")
    marker = _hostile_filter(repo, tmp_path)
    scan_workspace(ws)
    assert not marker.exists()
    memo = json.loads(_memo_path(ws).read_text(encoding="utf-8"))
    for entry in memo.values():
        if "config" in entry:
            entry["config"][1] = []  # "this repo has no filters"
    _memo_path(ws).write_text(json.dumps(memo), encoding="utf-8")
    git_module.forget_git_memo()
    time.sleep(1.1)
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    scan_workspace(ws)
    assert not marker.exists()


def test_worktree_config_is_never_stamped(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "app")
    _git(repo, "config", "extensions.worktreeConfig", "true")
    assert git_module.config_stamp(repo) is None


def test_an_imported_remote_must_look_like_a_normalised_remote(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "app")
    _git(repo, "remote", "add", "origin", "https://github.com/acme/app.git")
    git_module.forget_git_memo()
    stamp = git_module.config_stamp(repo)
    git_module.import_git_memo({str(repo): {"remote": [stamp, "https://u:secret@evil/x"]}})
    assert git_module.git_remote(repo) == "github.com/acme/app"


def test_full_scan_ignores_the_git_memo(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    repo = make_repo(ws, "app")
    scan_workspace(ws)
    memo = json.loads(_memo_path(ws).read_text(encoding="utf-8"))
    for entry in memo.values():
        entry["head"][1] = "deadbee"
    _memo_path(ws).write_text(json.dumps(memo), encoding="utf-8")
    git_module.forget_git_memo()
    result = scan_workspace(ws, use_cache=False)
    real = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    assert result.workspace.repo("app").head_sha == real  # type: ignore[union-attr]


def test_a_symbolic_ref_is_never_memoised(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "app")
    _git(repo, "symbolic-ref", "refs/heads/alias", "refs/heads/" + _branch(repo))
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/alias")
    assert git_module.head_stamp(repo) is None


def _branch(repo: Path) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), "branch", "--show-current"], capture_output=True, text=True
    )
    return done.stdout.strip()


def test_untracked_content_in_a_submodule_is_not_dirty(tmp_path: Path) -> None:
    lib = make_repo(tmp_path, "lib")
    app = make_repo(tmp_path, "app")
    _git(app, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(lib), "lib")
    _git(app, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "-m", "sub")
    (app / "lib" / "scratch.txt").write_text("x\n", encoding="utf-8")
    git_module.forget_git_memo()
    assert repo_state(app)[0].dirty == git_info(app).dirty


def test_a_warm_refresh_sees_new_git_ignored_live_files(tmp_path: Path) -> None:
    for name in ("api", "web"):
        repo = make_repo(tmp_path, name)
        (repo / "package.json").write_text(f'{{"name": "{name}"}}', encoding="utf-8")
        (repo / "scripts").mkdir()
        (repo / "scripts" / ".gitignore").write_text("dev.sh\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "-m", "x")
    assert not scan_workspace(tmp_path).workspace.edges
    script = tmp_path / "api" / "scripts" / "dev.sh"
    script.write_text("cd ../../web && npm run dev\n", encoding="utf-8")
    warm = scan_workspace(tmp_path).workspace
    assert [(e.source, e.target) for e in warm.edges] == [("api", "web")]


def test_the_file_index_is_compact(tmp_path: Path) -> None:
    import tracemalloc

    repo = tmp_path / "big"
    for d in range(20):
        (repo / f"d{d}").mkdir(parents=True)
        for f in range(150):
            (repo / f"d{d}" / f"f{f}.py").write_text("", encoding="utf-8")
    ctx = base_module.DetectorContext(
        tmp_path, RepoLocation(id="big", root=repo, app_roots=(repo,)), CairnConfig()
    )
    tracemalloc.start()
    before = tracemalloc.take_snapshot()
    count = sum(1 for _ in ctx.files(lambda name: name.endswith(".py")))
    after = tracemalloc.take_snapshot()
    tracemalloc.stop()
    retained = sum(s.size_diff for s in after.compare_to(before, "filename"))
    assert count == 3000 and retained / count < 300, retained / count


def test_the_read_cache_counts_memory_not_characters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(base_module, "READ_CACHE_BYTES", 1500)
    repo = tmp_path / "wide"
    repo.mkdir()
    (repo / "euro.py").write_text("€" * 900, encoding="utf-8")  # 900 chars, ~1.8 KB in memory
    ctx = base_module.DetectorContext(
        tmp_path, RepoLocation(id="wide", root=repo, app_roots=(repo,)), CairnConfig()
    )
    assert ctx.read(repo / "euro.py") is not None
    assert ctx.cached_bytes() == 0


def test_doctor_reports_an_unreadable_map(tmp_path: Path) -> None:
    (tmp_path / ".cairn").mkdir()
    (tmp_path / ".cairn" / "workspace.json").write_bytes(b"\xff\xfe\x00garbage")
    result = CliRunner().invoke(app, ["doctor", str(tmp_path)])
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "FAIL map:" in result.output


def test_the_perf_script_refuses_a_real_workspace(tmp_path: Path) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("perf_scan", ROOT / "bench" / "perf_scan.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / ".cairn").mkdir()
    (tmp_path / ".cairn" / "relations.yaml").write_text("edges: []\n", encoding="utf-8")
    make_repo(tmp_path, "my-real-app")
    with pytest.raises(SystemExit):
        module.main(["--repos", "1", "--files", "1", "--out", str(tmp_path)])
    assert (tmp_path / ".cairn" / "relations.yaml").is_file()


def test_rerun_only_retries_jobs_no_runner_picked_up() -> None:
    text = (ROOT / ".github" / "workflows" / "rerun.yml").read_text(encoding="utf-8")
    assert "not acquired by Runner" in text and "/annotations" in text
    # --failed only once every failed job is a runner-capacity one: real failures stand.
    assert '[ "$real" -eq 0 ]' in text and text.index('[ "$real" -eq 0 ]') < text.index("--failed")


def test_package_jobs_are_named_by_os_only() -> None:
    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    assert ci["jobs"]["package"]["name"] == "package (${{ matrix.os }})"


def test_writing_cards_looks_graphify_up_only_for_deep_indexes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cairn import providers
    from cairn.emit import write_outputs

    for name in ("a", "b", "c"):
        make_repo(tmp_path, name)
    calls = []
    real = providers.default_provider
    monkeypatch.setattr(providers, "default_provider", lambda: calls.append(1) or real())
    write_outputs(tmp_path, scan_workspace(tmp_path))
    assert calls == []
