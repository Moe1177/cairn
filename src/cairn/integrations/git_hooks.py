"""Opt-in git hooks that keep the map fresh after commits and merges (spec §8, §18)."""

import os
import shlex
from pathlib import Path

from cairn.errors import CairnError
from cairn.integrations.config_files import read_raw
from cairn.integrations.server_command import server_command
from cairn.render.markers import TOML_END, TOML_START, remove_block, upsert_block
from cairn.store.atomic import atomic_write_text
from cairn.store.workspace_store import load_workspace

HOOKS = ("post-commit", "post-merge")
_SHEBANG = "#!/bin/sh\n"


def hook_body(ws_root: Path) -> str:
    """Background refresh so commits never wait on cairn; Git for Windows runs hooks in sh too."""
    command = [*server_command()[:-1], "refresh", ws_root.resolve().as_posix(), "--quiet"]
    return f"({shlex.join(command)}) >/dev/null 2>&1 &"


def _hook_dirs(ws_root: Path) -> list[Path]:
    workspace = load_workspace(ws_root)
    if workspace is None:
        raise CairnError("No map found. Run `cairn scan` first.")
    dirs = [ws_root / r.path / ".git" / "hooks" for r in workspace.repos]
    return [d for d in dirs if d.parent.is_dir()]  # skip worktrees/submodules (.git is a file)


def install_hooks(ws_root: Path) -> int:
    body = hook_body(ws_root)
    dirs = _hook_dirs(ws_root)
    for hooks in dirs:
        for name in HOOKS:
            path = hooks / name
            raw = read_raw(path) or _SHEBANG
            atomic_write_text(path, upsert_block(raw, body, start=TOML_START, end=TOML_END))
            os.chmod(path, 0o755)
    return len(dirs)


def uninstall_hooks(ws_root: Path) -> int:
    count = 0
    for hooks in _hook_dirs(ws_root):
        touched = False
        for name in HOOKS:
            path = hooks / name
            raw = read_raw(path)
            if TOML_START not in raw:
                continue
            rest = remove_block(raw, start=TOML_START, end=TOML_END)
            touched = True
            if rest.strip() in ("", _SHEBANG.strip()):
                path.unlink()
            else:
                atomic_write_text(path, rest)
        count += touched
    return count
