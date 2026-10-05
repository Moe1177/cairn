"""Persist the generated workspace graph (.cairn/workspace.json)."""

from pathlib import Path

from pydantic import ValidationError

from cairn.errors import WorkspaceStoreError
from cairn.model.graph import Workspace
from cairn.paths import workspace_file
from cairn.store.atomic import atomic_write_text


def save_workspace(ws_root: Path, workspace: Workspace) -> Path:
    path = workspace_file(ws_root)
    atomic_write_text(path, workspace.model_dump_json(indent=2) + "\n")
    return path


def load_workspace(ws_root: Path) -> Workspace | None:
    path = workspace_file(ws_root)
    if not path.is_file():
        return None
    try:
        return Workspace.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise WorkspaceStoreError(
            f"{path} is unreadable or from an unsupported cairn version; "
            "run `cairn scan` to rebuild it."
        ) from exc
