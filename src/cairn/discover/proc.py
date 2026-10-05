"""Run external programs the same safe way everywhere (spec §20.1, §20.2).

- Output is decoded as UTF-8 with replacement, never the console code page.
- No console window flashes up on Windows when a GUI host (an editor's MCP client) runs cairn.
- A missing program, an OS error, or a timeout is reported as None, never raised.
"""

import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


@dataclass(frozen=True)
class Completed:
    returncode: int
    stdout: str
    stderr: str


def run_bytes(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: float = 10.0,
    env: Mapping[str, str] | None = None,
) -> tuple[int, bytes] | None:
    """(exit code, raw stdout), or None when the program couldn't run or timed out."""
    try:
        done = subprocess.run(
            list(args),
            cwd=cwd,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=dict(env) if env is not None else None,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return done.returncode, done.stdout or b""


def run_text(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: float = 10.0,
    env: Mapping[str, str] | None = None,
) -> Completed | None:
    try:
        done = subprocess.run(
            list(args),
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=dict(env) if env is not None else None,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return Completed(done.returncode, done.stdout or "", done.stderr or "")
