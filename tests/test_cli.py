from pathlib import Path

import pytest
from typer.testing import CliRunner

from cairn.cli import app
from cairn.paths import index_file
from tests.helpers import make_repo

runner = CliRunner()


@pytest.fixture(autouse=True)
def _cairn_home(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CAIRN_HOME", str(tmp_path / "home" / ".cairn"))
    monkeypatch.setenv("CAIRN_USER_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr("cairn.integrations.harnesses._claude_cli", lambda args: None)


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    make_repo(ws, "alpha", {"package.json": '{"name": "@acme/alpha"}'})
    make_repo(
        ws, "beta", {"package.json": '{"name": "beta", "dependencies": {"@acme/alpha": "1"}}'}
    )
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


def test_install_unknown_harness(tmp_path: Path) -> None:
    result = runner.invoke(app, ["install", "vim", str(_ws(tmp_path))])
    assert result.exit_code == 1
    assert "unknown harness" in result.output


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


def test_cli_output_survives_a_legacy_windows_console(tmp_path: Path) -> None:
    # Found while dogfooding: cp1252 consoles cannot encode "→".
    import os
    import subprocess
    import sys

    ws = _ws(tmp_path)
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"}
    for args in (["scan", str(ws)], ["status", str(ws)]):
        proc = subprocess.run(
            [sys.executable, "-c", "from cairn.cli import app; app()", *args],
            capture_output=True,
            env=env,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr.decode("cp1252", errors="replace")


def test_init_with_no_repos_does_not_offer_install(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    result = runner.invoke(app, ["init", str(empty), "--yes"])
    assert result.exit_code == 0
    assert "No git repos found" in result.output
    assert not (empty / "CLAUDE.md").exists()


def test_status_lists_ambiguous_edges(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    sql = "CREATE TABLE invoices (id int);\nCREATE TABLE ledgers (id int);\n"
    make_repo(ws, "a", {"db/1.sql": sql})
    make_repo(ws, "b", {"db/1.sql": sql})
    runner.invoke(app, ["scan", str(ws)])
    out = runner.invoke(app, ["status", str(ws)]).output
    assert "Unconfirmed links (1):" in out and "a->b:shares_db" in out
    assert "cairn annotate-edge" in out


def test_annotate_edge_rejects_and_rescans(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    sql = "CREATE TABLE invoices (id int);\nCREATE TABLE ledgers (id int);\n"
    make_repo(ws, "a", {"db/1.sql": sql})
    make_repo(ws, "b", {"db/1.sql": sql})
    runner.invoke(app, ["scan", str(ws)])
    result = runner.invoke(app, ["annotate-edge", "a->b:shares_db", str(ws), "--reject"])
    assert result.exit_code == 0, result.output
    assert "Mapped 2 repos and 0 relationships" in result.output
    bad = runner.invoke(app, ["annotate-edge", "a->b:shares_db", str(ws)])
    assert bad.exit_code == 1 and "--confirm, --reject, or --why" in bad.output


def test_serve_outside_a_workspace_starts_and_explains(tmp_path: Path, monkeypatch) -> None:
    # Phase 2b review: globally registered servers must not fail in unrelated projects.
    import cairn.mcp_server.server as srv

    built: list[object] = []

    class FakeServer:
        def run(self) -> None:
            built.append("ran")

    monkeypatch.setattr(
        srv, "build_server", lambda root, start=None: built.append((root, start)) or FakeServer()
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["serve"])
    assert result.exit_code == 0
    assert built[0] == (None, tmp_path) and built[1] == "ran"


def test_set_summary_cli_updates_index(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    runner.invoke(app, ["scan", str(ws)])
    result = runner.invoke(
        app,
        ["set-summary", "alpha", "-", str(ws), "--alias", "core"],
        input="Core shared library.\n",
    )
    assert result.exit_code == 0, result.output
    assert "- alpha (@acme/alpha, core): Core shared library" in index_file(ws).read_text(
        encoding="utf-8"
    )


def test_install_all_continues_past_a_broken_config(tmp_path: Path) -> None:
    # Review Focus 5
    ws = _ws(tmp_path)
    runner.invoke(app, ["scan", str(ws)])
    gemini = tmp_path / "home" / ".gemini" / "settings.json"
    gemini.parent.mkdir(parents=True)
    gemini.write_text("{broken", encoding="utf-8")
    result = runner.invoke(app, ["install", "all", str(ws)])
    assert result.exit_code == 1
    assert "gemini: error:" in result.output
    assert "Codex: pointer" in result.output and "Cursor:" in result.output
    status = runner.invoke(app, ["status", str(ws)]).output
    assert "Harnesses: claude, codex, cursor" in status


def test_install_all_survives_a_locked_config(tmp_path: Path, monkeypatch) -> None:
    import cairn.integrations.harnesses as h

    def locked(ws_root: Path, per_repo: bool) -> tuple[str, ...]:
        raise PermissionError(13, "The process cannot access the file", "settings.json")

    monkeypatch.setitem(h._INSTALLERS, "gemini", locked)
    ws = _ws(tmp_path)
    runner.invoke(app, ["scan", str(ws)])
    result = runner.invoke(app, ["install", "all", str(ws)])
    assert result.exit_code == 1
    assert "gemini: error:" in result.output and "Cursor:" in result.output


def test_refresh_quiet_and_verbose(materialize) -> None:
    ws = materialize("mini-eats").resolve()
    assert runner.invoke(app, ["scan", str(ws)]).exit_code == 0
    quiet = runner.invoke(app, ["refresh", str(ws), "--quiet"])
    assert quiet.exit_code == 0 and quiet.output == ""
    loud = runner.invoke(app, ["refresh", str(ws), "--verbose"])
    assert "4 from cache" in loud.output and "cairn scan at" in loud.output
    full = runner.invoke(app, ["scan", str(ws), "--full"])
    assert "0 from cache" in full.output
