"""Shared fixtures: materialize fixture workspaces as real git repos."""

from collections.abc import Callable
from pathlib import Path

import pytest

from cairn.bench.workspace import materialize as materialize_tree

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "workspaces"


@pytest.fixture(autouse=True)
def _isolated_homes(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch):
    """Every test gets throwaway harness homes, so none can write the developer's real
    ~/.cursor, ~/.codex, ~/.gemini or ~/.claude, even one that forgets to isolate itself.
    Tests that set their own homes override these."""
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("CAIRN_USER_HOME", str(home))
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("CAIRN_HOME", str(home / ".cairn-home"))


@pytest.fixture
def materialize(tmp_path: Path) -> Callable[..., Path]:
    def _make(name: str, remotes: dict[str, str] | None = None) -> Path:
        return materialize_tree(FIXTURES / name, tmp_path / name, remotes=remotes)

    return _make
