"""Opt-in git hooks that keep the map fresh after commits and merges (spec §8, §18).

cairn's block goes right after the shebang, so a hook that ends in `exit 0` or `exec ...`
still runs it, and uninstall removes exactly the bytes install added. Hooks that aren't
shell scripts, symlinked hooks (usually tracked files), and repos whose hooks live in
`core.hooksPath` (husky, lefthook) are skipped and reported, never edited.
"""

import os
import re
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cairn.discover.git import git_text
from cairn.errors import CairnError
from cairn.integrations.config_files import read_raw
from cairn.integrations.server_command import server_command
from cairn.render.markers import TOML_END, TOML_START
from cairn.store.atomic import atomic_write_text
from cairn.store.workspace_store import load_workspace

HOOKS = ("post-commit", "post-merge")
_SHEBANG = "#!/bin/sh\n"
_CREATED = "# cairn created this file; `cairn hooks uninstall` deletes it."
_SHELL = re.compile(r"#!\s*(?:\S*/)?(?:env\s+(?:-\S+\s+)*)?(?:sh|bash|dash|zsh|ksh|ash)\b")
_BLOCK = re.compile(re.escape(TOML_START) + r".*?" + re.escape(TOML_END) + r"(?:\r?\n)?", re.S)


@dataclass(frozen=True)
class HookReport:
    changed: tuple[str, ...] = ()
    skipped: tuple[tuple[str, str], ...] = ()


def hook_body(ws_root: Path) -> str:
    """Background refresh so commits never wait on cairn; Git for Windows runs hooks in sh too."""
    command = [*server_command()[:-1], "refresh", ws_root.resolve().as_posix(), "--quiet"]
    return f"({shlex.join(command)}) >/dev/null 2>&1 &"


def _hooks_dir(repo_root: Path) -> Path | str:
    """The repo's hooks folder, or why cairn won't write there."""
    if git_text(repo_root, ["config", "--get", "core.hooksPath"]):
        return (
            "core.hooksPath is set (husky, lefthook, ...); add "
            "`cairn refresh --quiet` to that hook manager instead"
        )
    found = git_text(repo_root, ["rev-parse", "--git-path", "hooks"])
    if not found:
        return "not a git repository git can read"
    path = Path(found)
    return path if path.is_absolute() else repo_root / path


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _with_block(raw: str, body: str) -> str:
    newline = _newline(raw) if raw else "\n"
    existing = _BLOCK.search(raw)
    created = not raw or (existing is not None and _CREATED in existing.group(0))
    lines = [TOML_START, *([_CREATED] if created else []), *body.splitlines(), TOML_END]
    block = newline.join(lines) + newline
    if existing is not None:
        return raw[: existing.start()] + block + raw[existing.end() :]
    if not raw:
        return _SHEBANG + block
    if not raw.startswith("#!"):
        return block + raw
    first, sep, rest = raw.partition("\n")
    if not sep:  # a lone shebang without a newline
        return first + newline + block
    return first + sep + block + rest


def _without_block(raw: str) -> str | None:
    """The hook as it was before install, or None when cairn created the file."""
    match = _BLOCK.search(raw)
    if match is None:
        return raw
    rest = raw[: match.start()] + raw[match.end() :]
    return None if _CREATED in match.group(0) and rest == _SHEBANG else rest


def _plan(
    ws_root: Path, edit: Callable[[str], str | None], *, installing: bool
) -> tuple[list[tuple[Path, str | None]], HookReport]:
    """Work out every write first, so one unreadable hook doesn't leave a half-done install."""
    workspace = load_workspace(ws_root)
    if workspace is None:
        raise CairnError("No map found. Run `cairn scan` first.")
    writes: list[tuple[Path, str | None]] = []
    changed: list[str] = []
    skipped: list[tuple[str, str]] = []
    for repo in workspace.repos:
        hooks = _hooks_dir(ws_root / repo.path)
        if isinstance(hooks, str):
            skipped.append((repo.id, hooks))
            continue
        repo_writes: list[tuple[Path, str | None]] = []
        complete = True
        for name in HOOKS:
            path = hooks / name
            if path.is_symlink():
                skipped.append((repo.id, f"{name} is a symlink (likely a tracked file)"))
                complete = False
                continue
            raw = read_raw(path)
            if raw and raw.startswith("#!") and not _SHELL.match(raw):
                skipped.append((repo.id, f"{name} is not a shell script"))
                complete = False
                continue
            updated = edit(raw)
            if updated != raw:
                repo_writes.append((path, updated))
        writes += repo_writes
        # Installing: every hook now runs cairn. Uninstalling: something was removed.
        if (installing and complete) or (not installing and repo_writes):
            changed.append(repo.id)
    return writes, HookReport(tuple(changed), tuple(skipped))


def _apply(writes: list[tuple[Path, str | None]]) -> None:
    for path, text in writes:
        if text is None:
            path.unlink(missing_ok=True)
            continue
        atomic_write_text(path, text)
        os.chmod(path, 0o755)


def install_hooks(ws_root: Path) -> HookReport:
    body = hook_body(ws_root)
    writes, report = _plan(ws_root, lambda raw: _with_block(raw, body), installing=True)
    _apply(writes)
    return report


def uninstall_hooks(ws_root: Path) -> HookReport:
    writes, report = _plan(ws_root, _without_block, installing=False)
    _apply(writes)
    return report
