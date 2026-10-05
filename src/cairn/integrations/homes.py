"""Where each harness keeps its user-level files. Tests redirect everything via env vars."""

import os
from pathlib import Path


def user_home() -> Path:
    override = os.environ.get("CAIRN_USER_HOME")
    return Path(override) if override else Path.home()


def claude_home() -> Path:
    return user_home() / ".claude"


def codex_home() -> Path:
    override = os.environ.get("CODEX_HOME")
    return Path(override) if override else user_home() / ".codex"


def gemini_home() -> Path:
    return user_home() / ".gemini"


def cursor_home() -> Path:
    return user_home() / ".cursor"
