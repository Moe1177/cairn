"""The Claude Code plugin (spec §27): what its session-start hook says, and whether it's on.

The plugin loads the index into each session itself instead of a block in CLAUDE.md. Its hook runs
`cairn context`, which prints, for the session's folder:
- inside a mapped workspace: the INDEX (trimmed to fit the hook's output limit), unless the
  workspace's CLAUDE.md already holds it;
- inside one repo of a folder of repos with no map: a short note so Claude can offer to build one;
- anywhere else: nothing.
"""

import json
import os
from pathlib import Path

from cairn.integrations.claude import is_installed
from cairn.integrations.homes import claude_home
from cairn.integrations.registry import find_workspace
from cairn.paths import index_file

PLUGIN_ENV = "CAIRN_PLUGIN"  # set by the plugin's launchers, so cairn knows who runs it
PLUGIN_NAME = "cairn"
# Claude Code keeps at most 10,000 characters of a hook's output in context.
CONTEXT_MAX = 9_000
MIN_REPOS = 2  # one repo needs no map of how repos connect
_MAX_SCAN = 500  # folders looked at when counting sibling repos


def plugin_enabled() -> bool:
    """Run through the plugin, or the plugin is enabled in the user's Claude Code settings."""
    if os.environ.get(PLUGIN_ENV) == "1":
        return True
    try:
        settings = json.loads((claude_home() / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    enabled = settings.get("enabledPlugins") if isinstance(settings, dict) else None
    if not isinstance(enabled, dict):
        return False
    return any(
        isinstance(key, str) and key.split("@", 1)[0] == PLUGIN_NAME and value is True
        for key, value in enabled.items()
    )


def session_start(start: Path | None = None) -> Path:
    """Where the session is: Claude Code's project folder, else the current directory."""
    if start is not None:
        return start
    project = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(project) if project else Path.cwd()


def session_context(start: Path, limit: int = CONTEXT_MAX) -> str:
    """What the plugin's hook adds to a session started in `start` ("" for nothing)."""
    note = _duplicate_note()
    body = _context_body(start, limit - len(note))
    return "\n\n".join(part for part in (body, note) if part)


def _duplicate_note() -> str:
    """Only the plugin runs this hook; a skill from `cairn install claude` beside it means
    every cairn tool and the skill show up twice, which costs context on every turn."""
    if not (claude_home() / "skills" / "cairn" / "SKILL.md").is_file():
        return ""
    return (
        "cairn: cairn is installed both as this plugin and with `cairn install claude`, so its "
        "tools and skill appear twice. Tell the user once that `cairn uninstall claude` removes "
        "the second copy."
    )


def _context_body(start: Path, limit: int) -> str:
    workspace = find_workspace(start) if start.is_dir() else None
    if workspace is not None:
        return _index_context(workspace, limit)
    unmapped = unmapped_folder(start)
    if unmapped is None:
        return ""
    folder, repos = unmapped
    return (
        f"cairn: {folder.as_posix()} holds {repos} git repos and has no cairn map yet. If the "
        "user's work involves more than one of these repos, offer once to build the map with "
        "the /cairn skill (it runs `cairn init` there, read-only for the repos); don't build it "
        "without asking."
    )


def unmapped_folder(start: Path) -> tuple[Path, int] | None:
    """The folder that holds the repos around `start` (its own repo's parent, or `start` itself
    when it holds repos), with how many it holds, if there are enough to map."""
    start = start.resolve()
    repo = next((p for p in (start, *start.parents) if (p / ".git").exists()), None)
    for folder in (repo.parent,) if repo is not None else (start,):
        count = _child_repos(folder)
        if count >= MIN_REPOS:
            return folder, count
    return None


def _child_repos(folder: Path) -> int:
    try:
        children = sorted(folder.iterdir())[:_MAX_SCAN]
    except OSError:
        return 0
    return sum(1 for child in children if child.is_dir() and (child / ".git").exists())


def _index_context(workspace: Path, limit: int) -> str:
    if is_installed(workspace):
        return ""  # CLAUDE.md already loads the index; saying it twice costs context
    try:
        index = index_file(workspace).read_text(encoding="utf-8")
    except OSError:
        return ""
    footer = (
        f"\n\nThis is the cairn map of {workspace.as_posix()}. Before exploring a repo, read "
        f"`.cairn/cards/<repo>.md` there, or ask the cairn MCP tools (resolve_repo, repo_card, "
        "related, find_across, query)."
    )
    return _fit(index.strip(), limit - len(footer), workspace) + footer


def _fit(index: str, budget: int, workspace: Path) -> str:
    """The index, cut at a whole line when it doesn't fit, saying how much was left out."""
    if len(index) <= budget:
        return index
    lines = index.splitlines()
    note_room = 200
    kept: list[str] = []
    size = 0
    for line in lines:
        if size + len(line) + 1 > budget - note_room:
            break
        kept.append(line)
        size += len(line) + 1
    left = sum(1 for line in lines[len(kept) :] if line.startswith("- "))
    kept.append(
        f"- …and {left} more repos: read {index_file(workspace).as_posix()} for the full list."
    )
    return "\n".join(kept)
