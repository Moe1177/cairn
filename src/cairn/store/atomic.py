"""Crash-safe file writes: write to a temp file in the same directory, then rename."""

import contextlib
import os
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
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        _replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise


def _replace(src: str, dest: Path) -> None:
    for attempt in range(_REPLACE_RETRIES):
        try:
            os.replace(src, dest)
            return
        except PermissionError:
            if os.name != "nt" or attempt == _REPLACE_RETRIES - 1:
                raise
            time.sleep(_REPLACE_DELAY)
