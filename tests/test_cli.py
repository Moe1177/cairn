from pathlib import Path

import pytest
from typer.testing import CliRunner

from cairn.cli import app
from cairn.paths import index_file
from tests.helpers import make_repo

runner = CliRunner()


@pytest.fixture(autouse=True)
def _cairn_home(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CAIRN_HOME", str(tmp_path / "home"))


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    make_repo(ws, "alpha", {"package.json": '{"name": "@acme/alpha"}'})
    make_repo(ws, "beta", {"package.json": '{"name": "beta", "dependencies": {"@acme/alpha": "1"}}'})
    return ws


def test_scan_writes_outputs_and_summarizes(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    result = runner.invoke(app, ["scan", str(ws)])
    assert result.exit_code == 0, result.output
    assert "Mapped 2 repos and 1 relationships (1 extracted)" in result.output
    assert index_file(ws).is_file()


def test_init_yes_installs_claude(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    result = runner.invoke(app, ["init", str(ws), "--yes"])
    assert result.exit_code == 0, result.output
    assert (ws / "CLAUDE.md").is_file()


def test_init_declined_skips_install(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    result = runner.invoke(app, ["init", str(ws)], input="n\n")
    assert result.exit_code == 0
    assert not (ws / "CLAUDE.md").exists()
    assert "cairn install claude" in result.output


def test_install_unsupported_harness(tmp_path: Path) -> None:
    result = runner.invoke(app, ["install", "codex", str(_ws(tmp_path))])
    assert result.exit_code == 1
    assert "not supported yet" in result.output


def test_install_then_uninstall(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    runner.invoke(app, ["scan", str(ws)])
    assert runner.invoke(app, ["install", "claude", str(ws)]).exit_code == 0
    removed = runner.invoke(app, ["uninstall", "claude", str(ws)])
    assert removed.exit_code == 0 and "removed" in removed.output
    assert not (ws / "CLAUDE.md").exists()


def test_status_before_and_after_scan(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    before = runner.invoke(app, ["status", str(ws)])
    assert before.exit_code == 1 and "cairn scan" in before.output
    runner.invoke(app, ["scan", str(ws)])
    after = runner.invoke(app, ["status", str(ws)])
    assert after.exit_code == 0
    assert "Repos: 2" in after.output and "Edges: 1" in after.output
    assert "Claude Code integration: not installed" in after.output


def test_scan_missing_directory_errors(tmp_path: Path) -> None:
    result = runner.invoke(app, ["scan", str(tmp_path / "nope")])
    assert result.exit_code == 1
    assert "error:" in result.output
