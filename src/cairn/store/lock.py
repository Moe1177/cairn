"""A cross-process lock on a workspace's .cairn/ so concurrent scans never interleave writes."""

import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from cairn.errors import CairnError
from cairn.paths import cairn_dir

_THREAD_LOCK = threading.RLock()
_HELD = threading.local()
_POLL = 0.05


@contextmanager
def workspace_lock(ws_root: Path, timeout: float = 60.0) -> Iterator[None]:
    """Serialize work across threads (RLock) and processes (OS file lock). Re-entrant per thread."""
    with _THREAD_LOCK:
        depth = getattr(_HELD, "depth", 0)
        if depth:
            _HELD.depth = depth + 1
            try:
                yield
            finally:
                _HELD.depth = depth
            return
        if not ws_root.is_dir():
            raise CairnError(f"{ws_root} is not a directory")  # never create the workspace itself
        path = cairn_dir(ws_root) / ".lock"
        path.parent.mkdir(exist_ok=True)
        with path.open("a+b") as handle:
            _acquire(handle.fileno(), timeout)
            _HELD.depth = 1
            try:
                yield
            finally:
                _HELD.depth = 0
                _release(handle.fileno())


def _acquire(fd: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            _lock(fd)
            return
        except OSError as exc:
            if time.monotonic() > deadline:
                raise CairnError("another cairn process is still updating this workspace") from exc
            time.sleep(_POLL)


if os.name == "nt":
    import msvcrt

    def _lock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _release(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _release(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)
