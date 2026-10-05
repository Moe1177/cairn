"""Crash-safe file writes: write to a temp file in the same directory, then rename."""

import contextlib
import os
import stat
import tempfile
import time
from pathlib import Path

# Windows refuses to replace a file another process (or thread) has open for a brief moment.
_REPLACE_RETRIES = 40
_REPLACE_DELAY = 0.05


def atomic_write_text(path: Path, text: str) -> None:
    """Atomically replace `path`'s content. A symlinked path keeps its link; the target is written."""
    if path.is_symlink():
        path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = _mode_for(path)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        if mode is not None:
            os.chmod(tmp_name, mode)  # mkstemp makes 0600; keep what the file had
        _replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise


def _mode_for(path: Path) -> int | None:
    """POSIX: the existing file's mode, or what a normal create would give (0666 & ~umask)."""
    if os.name == "nt":
        return None
    try:
        return stat.S_IMODE(os.stat(path).st_mode)
    except FileNotFoundError:
        umask = os.umask(0)
        os.umask(umask)
        return 0o666 & ~umask


def _replace(src: str, dest: Path) -> None:
    for attempt in range(_REPLACE_RETRIES):
        try:
            os.replace(src, dest)
            return
        except PermissionError:
            if os.name != "nt" or attempt == _REPLACE_RETRIES - 1:
                raise
            time.sleep(_REPLACE_DELAY)
