"""Install/uninstall cairn into each harness (spec §7, §17.1)."""

import os
import shlex
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from cairn.discover.files import crosses_link
from cairn.discover.proc import run_text
from cairn.errors import CairnError
from cairn.integrations import config_files as cf
from cairn.integrations.claude import install_claude, is_installed, uninstall_claude
from cairn.integrations.content import (
    SKILL_BODY,
    cursor_rule_mdc,
    gemini_command_toml,
    pointer_text,
    skill_markdown,
)
from cairn.integrations.homes import claude_home, codex_home, cursor_home, gemini_home
from cairn.integrations.registry import (
    list_workspaces,
    register_workspace,
    unregister_workspace,
)
from cairn.integrations.server_command import server_command
from cairn.store.workspace_store import load_workspace

HARNESSES = ("claude", "codex", "gemini", "cursor")
_RULE = ".cursor/rules/cairn.mdc"
Lines = tuple[str, ...]


def install_harness(name: str, ws_root: Path, *, per_repo: bool = False) -> Lines:
    newly_registered = ws_root.resolve().as_posix() not in list_workspaces()
    register_workspace(ws_root)  # pointers written by the installer must list this workspace
    try:
        lines = _INSTALLERS[name](ws_root, per_repo)
    except BaseException:
        if newly_registered and not installed_harnesses(ws_root):
            unregister_workspace(ws_root)  # a refused install leaves nothing behind
        raise
    _refresh_pointers()
    return lines


def uninstall_harness(name: str, ws_root: Path) -> Lines:
    lines = _UNINSTALLERS[name](ws_root)
    if not installed_harnesses(ws_root):
        unregister_workspace(ws_root)  # only once no harness uses this workspace any more
    _refresh_pointers()
    return lines


def installed_harnesses(ws_root: Path) -> Lines:
    checks = {
        "claude": lambda: is_installed(ws_root),
        "codex": lambda: cf.TOML_START_MARK in cf.read_raw(codex_home() / "config.toml"),
        "gemini": lambda: '"cairn"' in cf.read_raw(gemini_home() / "settings.json"),
        "cursor": lambda: '"cairn"' in cf.read_raw(cursor_home() / "mcp.json"),
    }
    return tuple(name for name in HARNESSES if _check(checks[name]))


def _check(probe: Callable[[], bool]) -> bool:
    try:
        return probe()
    except CairnError:
        return False  # an unreadable config can't contain a working cairn entry


def _claude_cli(args: list[str]) -> tuple[int, str] | None:
    """Run the `claude` CLI: (exit code, output), or None when it isn't installed or can't run."""
    exe = shutil.which("claude")
    if exe is None:
        return None
    done = run_text([exe, *args], timeout=60)
    return None if done is None else (done.returncode, done.stdout + done.stderr)


def _refresh_pointers() -> None:
    """Keep every installed global pointer listing all registered workspaces."""
    body = pointer_text(list_workspaces())
    for path, label in (
        (codex_home() / "AGENTS.md", "codex"),
        (gemini_home() / "GEMINI.md", "gemini"),
    ):
        if "<!-- cairn:start -->" in cf.read_raw(path):
            cf.set_marker_text(path, body, label=label)


def _install_claude(ws_root: Path, _per_repo: bool) -> Lines:
    from cairn.integrations.plugin import plugin_enabled

    if plugin_enabled():
        # The plugin brings the skill, the MCP server and the index; a second copy of each
        # would only duplicate tools and context.
        return ("Claude Code: the cairn plugin is enabled and already loads all of this.",)
    target = install_claude(ws_root)
    skill = claude_home() / "skills" / "cairn" / "SKILL.md"
    cf.write_owned(skill, skill_markdown())
    return (f"Claude Code: index added to {target}", f"Claude Code skill: {skill}", _register_mcp())


def _register_mcp() -> str:
    command = server_command()
    manual = f"claude mcp add --scope user cairn -- {_display(command)}"
    add = ["mcp", "add", "--scope", "user", "cairn", "--", *command]
    result = _claude_cli(add)
    if result is None:
        return f"Claude Code MCP: run `{manual}`"
    replaced = False
    if result[0] != 0 and "already exists" in result[1].lower():
        _claude_cli(["mcp", "remove", "--scope", "user", "cairn"])  # may point at an old path
        result, replaced = _claude_cli(add), True
    if result is None or result[0] != 0:
        reason = (result[1].strip().splitlines() or ["unknown error"])[0] if result else "not run"
        return f"Claude Code MCP: `claude mcp add` failed ({reason}); run `{manual}`"
    return f"Claude Code MCP: {'re-registered' if replaced else 'registered'} (user scope)"


def _uninstall_claude(ws_root: Path) -> Lines:
    removed = uninstall_claude(ws_root)
    cf.remove_owned(claude_home() / "skills" / "cairn" / "SKILL.md")
    _claude_cli(["mcp", "remove", "--scope", "user", "cairn"])
    return ("Claude Code: cairn removed." if removed else "Claude Code: cairn was not installed.",)


def _install_codex(ws_root: Path, _per_repo: bool) -> Lines:
    home = codex_home()
    cf.set_marker_text(home / "AGENTS.md", pointer_text(list_workspaces()), label="codex")
    cf.write_owned(home / "skills" / "cairn" / "SKILL.md", skill_markdown())
    cf.set_toml_server(home / "config.toml", server_command(), label="codex")
    return (f"Codex: pointer, skill, and MCP server installed in {home}",)


def _uninstall_codex(ws_root: Path) -> Lines:
    home = codex_home()
    cf.remove_marker_text(home / "AGENTS.md", label="codex")
    cf.remove_owned(home / "skills" / "cairn" / "SKILL.md")
    cf.remove_toml_server(home / "config.toml", label="codex")
    return ("Codex: cairn removed.",)


def _install_gemini(ws_root: Path, _per_repo: bool) -> Lines:
    home = gemini_home()
    cf.set_marker_text(home / "GEMINI.md", pointer_text(list_workspaces()), label="gemini")
    cf.write_owned(home / "commands" / "cairn.toml", gemini_command_toml())
    cf.set_json_server(home / "settings.json", server_command(), label="gemini")
    return (f"Gemini CLI: pointer, /cairn command, and MCP server installed in {home}",)


def _uninstall_gemini(ws_root: Path) -> Lines:
    home = gemini_home()
    cf.remove_marker_text(home / "GEMINI.md", label="gemini")
    cf.remove_owned(home / "commands" / "cairn.toml")
    cf.remove_json_server(home / "settings.json", label="gemini")
    return ("Gemini CLI: cairn removed.",)


def _install_cursor(ws_root: Path, per_repo: bool) -> Lines:
    home = cursor_home()
    cf.write_owned(home / "commands" / "cairn.md", SKILL_BODY)
    # Cursor starts stdio servers outside the project; it expands ${workspaceFolder} itself.
    command = [*server_command(), "--from", "${workspaceFolder}"]
    cf.set_json_server(home / "mcp.json", command, label="cursor")
    lines = [f"Cursor: /cairn command and MCP server installed in {home}"]
    if per_repo:
        count, skipped = _cursor_rules(ws_root, add=True)
        lines.append(f"Cursor: pointer rule added to {count} repos (git-excluded)")
        lines += [f"Cursor: skipped {repo}: {why}" for repo, why in skipped]
    return tuple(lines)


def _uninstall_cursor(ws_root: Path) -> Lines:
    home = cursor_home()
    cf.remove_owned(home / "commands" / "cairn.md")
    cf.remove_json_server(home / "mcp.json", label="cursor")
    count, _ = _cursor_rules(ws_root, add=False)
    return (f"Cursor: cairn removed (rules removed from {count} repos).",)


def _cursor_rules(ws_root: Path, *, add: bool) -> tuple[int, list[tuple[str, str]]]:
    workspace = load_workspace(ws_root)
    if workspace is None:
        if add:
            raise CairnError("No map found. Run `cairn scan` first.")
        return 0, []  # nothing to clean per repo; the global cleanup already happened
    count = 0
    skipped: list[tuple[str, str]] = []
    for repo in workspace.repos:
        root = ws_root / repo.path
        if not (root / ".git").is_dir():
            continue  # worktrees/submodules keep .git as a file; leave them alone
        exclude = root / ".git" / "info" / "exclude"
        if crosses_link(root, root / _RULE) or crosses_link(root, exclude):
            # A committed link (e.g. `.cursor` -> elsewhere) would redirect the write.
            skipped.append((repo.id, "the rule path goes through a symlink or junction"))
            continue
        if add:
            cf.write_owned(root / _RULE, cursor_rule_mdc(ws_root.resolve().as_posix()))
            _set_exclude(exclude, present=True)
            count += 1
        elif cf.remove_owned(root / _RULE):
            _set_exclude(exclude, present=False)
            count += 1
    return count, skipped


def _set_exclude(exclude: Path, *, present: bool) -> None:
    lines = [line for line in cf.read_raw(exclude).splitlines() if line.strip() != _RULE]
    if present:
        lines.append(_RULE)
    cf.write_owned(exclude, "\n".join(lines) + "\n")


_INSTALLERS: dict[str, Callable[[Path, bool], Lines]] = {
    "claude": _install_claude,
    "codex": _install_codex,
    "gemini": _install_gemini,
    "cursor": _install_cursor,
}
_UNINSTALLERS: dict[str, Callable[[Path], Lines]] = {
    "claude": _uninstall_claude,
    "codex": _uninstall_codex,
    "gemini": _uninstall_gemini,
    "cursor": _uninstall_cursor,
}


def _display(command: list[str], *, windows: bool | None = None) -> str:
    """Quote a command for the user's shell (cmd/PowerShell on Windows, POSIX elsewhere)."""
    on_windows = os.name == "nt" if windows is None else windows
    return subprocess.list2cmdline(command) if on_windows else shlex.join(command)
