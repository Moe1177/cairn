"""Shared fixtures: materialize fixture workspaces as real git repos."""

from collections.abc import Callable
from pathlib import Path

import pytest

from cairn.bench.workspace import materialize as materialize_tree

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "workspaces"


@pytest.fixture
def materialize(tmp_path: Path) -> Callable[..., Path]:
    def _make(name: str, remotes: dict[str, str] | None = None) -> Path:
        return materialize_tree(FIXTURES / name, tmp_path / name, remotes=remotes)

    return _make
