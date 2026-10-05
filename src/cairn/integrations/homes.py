"""Where each harness keeps its user-level files. Tests redirect everything via env vars."""

import os
from pathlib import Path


def user_home() -> Path:
    override = os.environ.get("CAIRN_USER_HOME")
    return Path(override) if override else Path.home()


def claude_home() -> Path:
    """$CLAUDE_CONFIG_DIR when set (Claude Code reads skills from there), else ~/.claude.
    CAIRN_USER_HOME wins so tests never touch a real config."""
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    if override and not os.environ.get("CAIRN_USER_HOME"):
        return Path(override)
    return user_home() / ".claude"


def codex_home() -> Path:
    override = os.environ.get("CODEX_HOME")
    return Path(override) if override else user_home() / ".codex"


def gemini_home() -> Path:
    return user_home() / ".gemini"


def cursor_home() -> Path:
    return user_home() / ".cursor"
