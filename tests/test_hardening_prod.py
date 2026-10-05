"""Phase 2e Task 9 (spec §20.3): production behaviour."""

import threading
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

import cairn.scan as scan_module
from cairn.cli import app
from cairn.discover.git import GitInfo
from cairn.emit import write_outputs
from cairn.integrations import registry
from cairn.mcp_server import tools
from cairn.scan import scan_workspace
from cairn.store.lock import workspace_lock
from tests.helpers import make_repo


def test_missing_git_warns_once_and_still_maps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_repo(tmp_path, "web")
    make_repo(tmp_path, "api")
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    result = scan_workspace(tmp_path)
    assert {r.id for r in result.workspace.repos} == {"web", "api"}
    assert sum("git not found" in w for w in result.warnings) == 1


def test_io_errors_are_one_line_errors(tmp_path: Path) -> None:
    make_repo(tmp_path, "web")
    (tmp_path / ".cairn").write_text("not a folder", encoding="utf-8")
    result = CliRunner().invoke(app, ["scan", str(tmp_path)])
    assert result.exit_code == 1 and isinstance(result.exception, SystemExit)
    assert result.output.startswith("error: ")
    assert app.pretty_exceptions_enable is False


def test_empty_folder_scan_writes_nothing(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["scan", str(tmp_path)])
    assert result.exit_code == 0
    assert "No git repos found" in result.output
    assert not (tmp_path / ".cairn").exists()


def test_large_workspaces_scan_repos_in_parallel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for i in range(40):
        make_repo(tmp_path, f"svc-{i:02d}")

    def slow_git(root: Path, timeout: float = 5.0) -> GitInfo:
        time.sleep(0.05)
        return GitInfo()

    monkeypatch.setattr(scan_module, "git_info", slow_git)
    start = time.perf_counter()
    result = scan_workspace(tmp_path)
    assert len(result.workspace.repos) == 40
    assert time.perf_counter() - start < 1.5  # serially the git calls alone take 2 s


def test_mcp_answers_from_the_last_map_while_another_scan_runs(tmp_path: Path) -> None:
    make_repo(tmp_path, "web")
    write_outputs(tmp_path, scan_workspace(tmp_path))
    held, release = threading.Event(), threading.Event()

    def other_process() -> None:
        with workspace_lock(tmp_path):
            held.set()
            release.wait(30)

    worker = threading.Thread(target=other_process)
    worker.start()
    held.wait(5)
    try:
        start = time.perf_counter()
        text = tools.card_text(tmp_path, "web")
        assert time.perf_counter() - start < 8
        assert "# web" in text and "may be slightly stale" in text
    finally:
        release.set()
        worker.join()


def test_concurrent_registrations_are_all_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CAIRN_HOME", str(tmp_path / "ch"))
    original = registry._save

    def slow_save(workspaces: tuple[str, ...]) -> None:
        time.sleep(0.05)  # widen the read-modify-write window
        original(workspaces)

    monkeypatch.setattr(registry, "_save", slow_save)
    folders = [tmp_path / f"ws{i}" for i in range(6)]
    for folder in folders:
        folder.mkdir()
    threads = [threading.Thread(target=registry.register_workspace, args=(f,)) for f in folders]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(registry.list_workspaces()) == 6
