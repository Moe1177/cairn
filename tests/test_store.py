import os
from pathlib import Path

import pytest

from cairn.errors import WorkspaceStoreError
from cairn.model.graph import Repo, Workspace
from cairn.paths import workspace_file
from cairn.store.atomic import atomic_write_text
from cairn.store.workspace_store import load_workspace, save_workspace


def _ws() -> Workspace:
    return Workspace(workspace_root="/ws", generated_at="t", repos=(Repo(id="a", path="a"),))


def test_atomic_write_creates_parents_and_keeps_newlines(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "file.md"
    atomic_write_text(target, "a\nb\n")
    assert target.read_bytes() == b"a\nb\n"


def test_failed_write_leaves_original_and_no_temp_files(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "file.md"
    target.write_text("original", encoding="utf-8")

    def boom(src: str, dst: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "original"
    assert [p.name for p in tmp_path.iterdir()] == ["file.md"]


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    save_workspace(tmp_path, _ws())
    assert load_workspace(tmp_path) == _ws()


def test_load_missing_returns_none(tmp_path: Path) -> None:
    assert load_workspace(tmp_path) is None


def test_load_corrupt_raises_actionable_error(tmp_path: Path) -> None:
    path = workspace_file(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(WorkspaceStoreError) as info:
        load_workspace(tmp_path)
    assert "cairn scan" in str(info.value)


def test_load_future_schema_raises(tmp_path: Path) -> None:
    path = workspace_file(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text('{"schema_version": 2, "workspace_root": "/ws", "generated_at": "t"}', encoding="utf-8")
    with pytest.raises(WorkspaceStoreError):
        load_workspace(tmp_path)
