"""0.7.1: a deep build that fails isn't retried by every refresh until the repo changes."""

import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cairn import deep as deep_ops
from cairn import providers
from cairn.cli import app
from cairn.providers.graphify import GraphifyProvider
from cairn.store.workspace_store import load_workspace
from tests.test_deep_surfaces import ws  # noqa: F401  (fixture: two repos, a fake graphify)


def _cli(*args: str) -> str:
    return CliRunner().invoke(app, list(args)).output


def _stale_selection(ws: Path) -> list[str]:  # noqa: F811
    workspace = load_workspace(ws)
    assert workspace is not None
    return [r.id for r in deep_ops.select_repos(ws, workspace, [], every=False, stale=True)]


def _failing(monkeypatch: pytest.MonkeyPatch) -> None:
    """graphify that fails: the fake reads FAKE_FAIL, passed through the allowlisted env."""
    working = providers.default_provider()
    failing = GraphifyProvider(executable=working.executable, extra_env={"FAKE_FAIL": "1"})
    monkeypatch.setattr(providers, "default_provider", lambda: failing)


def _working(monkeypatch: pytest.MonkeyPatch, provider: GraphifyProvider) -> None:
    monkeypatch.setattr(providers, "default_provider", lambda: provider)


def _edit(ws: Path, text: str) -> None:  # noqa: F811
    time.sleep(1.1)  # a new mtime, so the working tree's fingerprint changes
    (ws / "app" / "auth.py").write_text(text, encoding="utf-8")


def test_a_failed_rebuild_waits_until_the_repo_changes(
    ws: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cli("deep", "build", "app", "-w", str(ws))
    _edit(ws, "def login():\n    return 1\n")
    assert _stale_selection(ws) == ["app"]
    _failing(monkeypatch)
    assert "failed" in _cli("deep", "build", "app", "-w", str(ws))
    assert _stale_selection(ws) == []  # unchanged since it failed: refresh leaves it alone
    _edit(ws, "def login():\n    return 2\n")
    assert _stale_selection(ws) == ["app"]  # changed: worth another try


def test_an_explicit_build_retries_and_success_clears_the_failure(
    ws: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _cli("deep", "build", "app", "-w", str(ws))
    _edit(ws, "def login():\n    return 1\n")
    working = providers.default_provider()
    _failing(monkeypatch)
    _cli("deep", "build", "app", "-w", str(ws))
    assert "last build failed" in _cli("deep", "status", "-w", str(ws))
    _working(monkeypatch, working)
    assert "app: 1 symbols indexed" in _cli("deep", "build", "app", "-w", str(ws))
    assert "last build failed" not in _cli("deep", "status", "-w", str(ws))
