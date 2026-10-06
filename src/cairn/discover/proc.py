"""Run external programs the same safe way everywhere (spec §20.1, §20.2).

- Output is decoded as UTF-8 with replacement, never the console code page.
- No console window flashes up on Windows when a GUI host (an editor's MCP client) runs cairn.
- A missing program, an OS error, or a timeout is reported as None, never raised.
"""

import contextlib
import os
import signal
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
_NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0


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


def run_text_tree(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: float = 10.0,
    env: Mapping[str, str] | None = None,
) -> Completed | None:
    """Like run_text, for programs that spawn children (console-script launchers, shims).

    Output goes to temp files, not pipes, so a child holding them can't stall the wait, and a
    timeout kills the whole process tree rather than only the launcher.
    """
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            proc = subprocess.Popen(
                list(args),
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                env=dict(env) if env is not None else None,
                creationflags=_NO_WINDOW | _NEW_GROUP,
                start_new_session=os.name != "nt",
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            return None
        return Completed(code, _read(out), _read(err))


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=30,
                check=False,
                creationflags=_NO_WINDOW,
            )
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    proc.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=10)


def _read(handle: IO[bytes], limit: int = 1_000_000) -> str:
    handle.seek(0)
    return handle.read(limit).decode("utf-8", errors="replace")
