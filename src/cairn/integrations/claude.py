"""Claude Code integration: the INDEX inside the workspace's parent CLAUDE.md.

Claude Code loads CLAUDE.md files from parent directories of the working
directory, so a block here is visible from inside every repo in the workspace.
"""

from collections.abc import Callable
from pathlib import Path

from cairn.errors import CairnError
from cairn.integrations.registry import register_workspace, unregister_workspace
from cairn.paths import backups_dir, index_file
from cairn.render.markers import END, START, remove_block, upsert_block
from cairn.store.atomic import atomic_write_text

_BACKUP_NAME = "CLAUDE.md.orig"


def claude_md(ws_root: Path) -> Path:
    return ws_root / "CLAUDE.md"


def is_installed(ws_root: Path) -> bool:
    return START in _read(claude_md(ws_root))


def install_claude(ws_root: Path) -> Path:
    index = index_file(ws_root)
    if not index.is_file():
        raise CairnError("No .cairn/INDEX.md found; run `cairn scan` first.")
    target = claude_md(ws_root)
    original = _read(target)
    updated = _checked(target, lambda: upsert_block(original, _read(index)))
    _backup_once(ws_root, original)
    atomic_write_text(target, updated)
    register_workspace(ws_root)
    return target


def uninstall_claude(ws_root: Path) -> bool:
    target = claude_md(ws_root)
    original = _read(target)
    if START not in original and END not in original:
        unregister_workspace(ws_root)
        return False
    updated = _checked(target, lambda: remove_block(original))
    unregister_workspace(ws_root)
    if updated.strip():
        atomic_write_text(target, updated)
    else:
        target.unlink()
    return True


def sync_claude(ws_root: Path) -> bool:
    if not is_installed(ws_root):
        return False
    install_claude(ws_root)
    return True


def _checked(target: Path, edit: Callable[[], str]) -> str:
    try:
        return edit()
    except CairnError as exc:
        raise CairnError(f"{target}: {exc} The file was left unchanged.") from exc


def _read(path: Path) -> str:
    if not path.is_file():
        return ""
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def _backup_once(ws_root: Path, original: str) -> None:
    backup = backups_dir(ws_root) / _BACKUP_NAME
    if original and START not in original and not backup.exists():
        atomic_write_text(backup, original)
