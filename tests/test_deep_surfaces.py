"""Phase 3 Task 3: deep indexes on the CLI, MCP, cards and status (spec §23)."""

import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cairn import providers
from cairn.bench.workspace import materialize
from cairn.cli import app
from cairn.emit import write_outputs
from cairn.mcp_server import tools
from cairn.paths import cards_dir
from cairn.providers.graphify import GraphifyProvider
from cairn.scan import scan_workspace
from tests.test_graphify_provider import _fake_graphify


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    src = tmp_path / "src"
    for name in ("app", "billing"):
        (src / name).mkdir(parents=True)
        (src / name / ".fixture-repo").write_text("", encoding="utf-8")
        (src / name / "auth.py").write_text("def login():\n    return True\n", encoding="utf-8")
    root = materialize(src, tmp_path / "ws").resolve()
    write_outputs(root, scan_workspace(root))
    fake = GraphifyProvider(executable=_fake_graphify(tmp_path))
    monkeypatch.setattr(providers, "default_provider", lambda: fake)
    return root


def _cli(*args: str) -> str:
    result = CliRunner().invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def test_build_status_and_clear(ws: Path) -> None:
    out = _cli("deep", "build", "--all", "-w", str(ws))
    assert "app: 1 symbols indexed" in out and "billing: 1 symbols indexed" in out
    status = _cli("deep", "status", str(ws))
    assert "app" in status and "1 symbols" in status and "fresh" in status
    assert "Deep indexes: app, billing" in _cli("status", str(ws))
    _cli("deep", "clear", "billing", "-w", str(ws))
    assert not (ws / ".cairn" / "deep" / "billing").exists()
    assert (ws / ".cairn" / "deep" / "app").exists()


def test_query_names_the_deep_index_symbol_on_grep_s_hit(ws: Path) -> None:
    _cli("deep", "build", "app", "-w", str(ws))
    answer = tools.query_text(ws, "app", "where is login handled?")
    assert "auth.py:1 login()" in answer and "stale" not in answer


def test_query_says_when_the_index_is_stale_or_missing(ws: Path) -> None:
    _cli("deep", "build", "app", "-w", str(ws))
    time.sleep(1.1)
    (ws / "app" / "auth.py").write_text("def login():\n    return False\n", encoding="utf-8")
    assert "may be stale" in tools.query_text(ws, "app", "logins")  # the graph answers
    missing = tools.query_text(ws, "billing", "warehouse robot")  # nothing found
    assert "cairn deep build billing" in missing


def test_cards_show_the_deeper_section(ws: Path) -> None:
    _cli("deep", "build", "app", "-w", str(ws))
    write_outputs(ws, scan_workspace(ws))
    card = (cards_dir(ws) / "app.md").read_text(encoding="utf-8")
    assert "## Deeper" in card and "graphify index: 1 symbols" in card
    assert "## Deeper" not in (cards_dir(ws) / "billing.md").read_text(encoding="utf-8")


def test_refresh_deep_rebuilds_only_stale_indexes(ws: Path) -> None:
    _cli("deep", "build", "--all", "-w", str(ws))
    built = {
        r: (ws / ".cairn" / "deep" / r / "cairn-deep.json").stat().st_mtime_ns
        for r in ("app", "billing")
    }
    time.sleep(1.1)
    (ws / "app" / "auth.py").write_text("def login():\n    return 2\n", encoding="utf-8")
    out = _cli("refresh", "--deep", str(ws))
    assert (
        "app: 1 symbols indexed" in out
        and "billing" not in out.split("Mapped", 1)[-1].split("\n", 1)[-1]
    )
    after = {
        r: (ws / ".cairn" / "deep" / r / "cairn-deep.json").stat().st_mtime_ns
        for r in ("app", "billing")
    }
    assert after["app"] != built["app"] and after["billing"] == built["billing"]


def test_build_without_graphify_explains_how_to_install(
    ws: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        providers, "default_provider", lambda: GraphifyProvider(executable=str(ws / "nope"))
    )
    result = CliRunner().invoke(app, ["deep", "build", "app", "-w", str(ws)])
    assert result.exit_code == 1 and "cairnmap[graphify]" in result.output


def test_clear_only_removes_existing_deep_indexes(ws: Path) -> None:
    outside = ws / ".cairn" / "keep"
    outside.mkdir()
    result = CliRunner().invoke(app, ["deep", "clear", "../keep", "-w", str(ws)])
    assert result.exit_code == 1 and "no deep index for" in result.output
    assert outside.is_dir()
