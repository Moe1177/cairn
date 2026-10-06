"""Phase 5 Task 7: the Phase 3 review's deferred minors (spec §23)."""

import json
import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cairn import deep as deep_ops
from cairn.cli import app
from cairn.emit import write_outputs
from cairn.mcp_server import tools
from cairn.paths import cards_dir
from cairn.providers.graph import hubs, load_graph
from cairn.scan import scan_workspace
from cairn.store.workspace_store import load_workspace
from tests.test_deep_surfaces import ws  # noqa: F401  (fixture)


def _cli(*args: str) -> str:
    result = CliRunner().invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def test_refresh_deep_writes_a_scan_taken_after_the_build(
    ws: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cli("deep", "build", "app", "-w", str(ws))
    (ws / "app" / "auth.py").write_text("def login():\n    return 3\n", encoding="utf-8")
    real_build = deep_ops.build

    def build_then_add_a_repo(*args, **kwargs):  # type: ignore[no-untyped-def]
        out = real_build(*args, **kwargs)
        late = ws / "late"  # appears while the (slow) build runs
        late.mkdir()
        subprocess.run(["git", "-C", str(late), "init", "-q"], check=True)
        return out

    monkeypatch.setattr(deep_ops, "build", build_then_add_a_repo)
    _cli("refresh", "--deep", str(ws))
    workspace = load_workspace(ws)
    assert workspace is not None and workspace.repo("late") is not None


def test_refresh_deep_quiet_prints_nothing(ws: Path) -> None:  # noqa: F811
    _cli("deep", "build", "app", "-w", str(ws))
    (ws / "app" / "auth.py").write_text("def login():\n    return 4\n", encoding="utf-8")
    assert _cli("refresh", "--deep", "--quiet", str(ws)).strip() == ""


def test_build_stale_says_when_nothing_is_stale(ws: Path) -> None:  # noqa: F811
    assert "No stale deep indexes." in _cli("deep", "build", "--stale", "-w", str(ws))


def test_deep_status_takes_the_workspace_like_build_and_clear(ws: Path) -> None:  # noqa: F811
    _cli("deep", "build", "app", "-w", str(ws))
    assert "app: 1 symbols" in _cli("deep", "status", "-w", str(ws))
    assert "app: 1 symbols" in _cli("deep", "status", str(ws))


def test_a_partial_index_says_rebuild(ws: Path) -> None:  # noqa: F811
    _cli("deep", "build", "app", "-w", str(ws))
    (ws / ".cairn" / "deep" / "app" / "graphify-out" / "graph.json").unlink()
    answer = tools.query_text(ws, "app", "login")
    assert "incomplete" in answer and "cairn deep build app" in answer
    write_outputs(ws, scan_workspace(ws))
    card = (cards_dir(ws) / "app.md").read_text(encoding="utf-8")
    assert "## Deeper" in card and "incomplete" in card and "ask `query`" not in card


def test_hubs_are_symbols_with_a_source_file(tmp_path: Path) -> None:
    nodes = [{"id": "np", "label": "numpy"}] + [
        {"id": f"f{i}", "label": f"f{i}()", "source_file": "a.py", "source_location": f"L{i + 1}"}
        for i in range(3)
    ]
    links = [{"source": f"f{i}", "target": "np", "relation": "imports"} for i in range(3)]
    links.append({"source": "f0", "target": "f1", "relation": "calls"})
    path = tmp_path / "graph.json"
    path.write_text(json.dumps({"nodes": nodes, "links": links}), encoding="utf-8")
    graph = load_graph(path)
    assert graph is not None and "numpy" not in hubs(graph, 5)
    assert hubs(graph, 5)[:2] == ["f0()", "f1()"]


def test_graphify_is_found_in_the_interpreter_scripts_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cairn.providers import graphify as module

    scripts = tmp_path / "Scripts"
    scripts.mkdir()
    exe = scripts / ("graphify.exe" if os.name == "nt" else "graphify")
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(module.sys, "executable", str(tmp_path / "python.exe"))
    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        module.sysconfig,
        "get_path",
        lambda name, scheme=None: str(scripts) if name == "scripts" and scheme is None else None,
    )
    assert module._find_executable() == str(exe)
