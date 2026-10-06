"""Phase 5 Task 6: `cairn doctor`, shell completion, and "used by" on INDEX lines (spec §22)."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from cairn.cli import app
from cairn.model.graph import Confidence, Edge, EdgeType, Repo, Workspace
from cairn.render.index import render_index
from cairn.render.tokens import estimate_tokens


def _edge(source: str, target: str, kind: EdgeType, confidence=Confidence.EXTRACTED) -> Edge:
    return Edge(source=source, target=target, type=kind, confidence=confidence, score=1.0)


def _ws(*edges: Edge) -> Workspace:
    ids = ("api", "billing", "mobile", "ui", "web", "worker")
    return Workspace(
        workspace_root="/ws",
        generated_at="t",
        repos=tuple(Repo(id=i, path=i) for i in ids),
        edges=edges,
    )


def _line(text: str, repo: str) -> str:
    return next(line for line in text.splitlines() if line.startswith(f"- {repo}"))


def test_index_lines_say_who_uses_a_repo() -> None:
    ws = _ws(
        _edge("web", "api", EdgeType.CALLS_HTTP),
        _edge("mobile", "api", EdgeType.CALLS_HTTP),
        _edge("worker", "api", EdgeType.GRPC, Confidence.INFERRED),
        _edge("billing", "api", EdgeType.COMPOSE_LINK),
        _edge("web", "ui", EdgeType.DEPENDS_ON_PACKAGE),
    )
    text = render_index(ws, {})
    assert _line(text, "api").endswith(" · used by billing, mobile, web +1")
    assert _line(text, "ui").endswith(" · used by web")
    assert "used by" not in _line(text, "web")
    assert estimate_tokens(_line(text, "api")) <= 30


def test_used_by_ignores_weak_symmetric_and_undirected_links() -> None:
    ws = _ws(
        _edge("web", "api", EdgeType.CALLS_HTTP, Confidence.AMBIGUOUS),
        _edge("billing", "api", EdgeType.SHARES_DB),
        _edge("worker", "api", EdgeType.MENTIONS),
        _edge("worker", "api", EdgeType.PUBSUB),
    )
    assert "used by" not in render_index(ws, {})


def _healthy(tmp_path: Path) -> Path:
    from tests.test_warm_refresh import make_repo

    make_repo(tmp_path, "api")
    result = CliRunner().invoke(app, ["scan", str(tmp_path)])
    assert result.exit_code == 0, result.output
    return tmp_path


def test_doctor_reports_a_healthy_setup(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["doctor", str(_healthy(tmp_path))])
    assert result.exit_code == 0, result.output
    for name in ("python", "git", "map", "write access", "harnesses", "graphify"):
        assert f" {name}:" in result.output, name
    assert "FAIL" not in result.output


def test_doctor_fails_without_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import cairn.doctor as doctor

    ws = _healthy(tmp_path)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    result = CliRunner().invoke(app, ["doctor", str(ws)])
    assert result.exit_code == 1
    assert "FAIL git:" in result.output


def test_doctor_warns_when_there_is_no_map(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["doctor", str(tmp_path)])
    assert "WARN map:" in result.output and "cairn scan" in result.output


def test_shell_completion_is_available() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert "--install-completion" in result.output
