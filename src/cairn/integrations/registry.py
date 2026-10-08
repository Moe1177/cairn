"""~/.cairn/registry.json: workspaces this machine has mapped (used by global pointers)."""

import json
import os
from pathlib import Path

from cairn.errors import CairnInputError
from cairn.paths import workspace_file
from cairn.store.atomic import atomic_write_text
from cairn.store.lock import file_lock


def cairn_home() -> Path:
    override = os.environ.get("CAIRN_HOME")
    return Path(override) if override else Path.home() / ".cairn"


def registry_file() -> Path:
    return cairn_home() / "registry.json"


def list_workspaces() -> tuple[str, ...]:
    path = registry_file()
    if not path.is_file():
        return ()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise CairnInputError(str(path), f"invalid JSON: {exc}") from exc
    workspaces = data.get("workspaces") if isinstance(data, dict) else None
    if not isinstance(workspaces, list) or not all(isinstance(w, str) for w in workspaces):
        raise CairnInputError(str(path), 'expected {"workspaces": [<path>, ...]}')
    return tuple(workspaces)


def register_workspace(ws_root: Path) -> None:
    entry = ws_root.resolve().as_posix()
    with file_lock(registry_file().with_suffix(".lock")):
        current = list_workspaces()
        if not any(_same_folder(entry, known) for known in current):
            _save((*current, entry))


def _same_folder(a: str, b: str) -> bool:
    """Equal paths, or the same folder spelled differently on a case-insensitive filesystem."""
    if a == b:
        return True
    try:
        return a.casefold() == b.casefold() and os.path.samefile(a, b)
    except OSError:
        return False


def unregister_workspace(ws_root: Path) -> None:
    entry = ws_root.resolve().as_posix()
    with file_lock(registry_file().with_suffix(".lock")):
        current = list_workspaces()
        kept = tuple(w for w in current if not _same_folder(entry, w))
        if kept != current:
            _save(kept)


def _save(workspaces: tuple[str, ...]) -> None:
    atomic_write_text(
        registry_file(), json.dumps({"workspaces": sorted(workspaces)}, indent=2) + "\n"
    )


def find_workspace(start: Path) -> Path | None:
    """Nearest folder at or above `start` with a cairn map, else a registered ancestor."""
    start = start.resolve()
    for folder in (start, *start.parents):
        if workspace_file(folder).is_file() and not _inside_git_repo(folder):
            return folder
    for entry in list_workspaces():
        root = Path(entry)
        if root == start or root in start.parents:
            return root
    return None


def _inside_git_repo(folder: Path) -> bool:
    """A workspace contains repos; a `.cairn/` inside a repo was committed there, so its map
    (repo ids, paths) is untrusted input and is never served (spec §20.1)."""
    return any((p / ".git").exists() for p in (folder, *folder.parents))
