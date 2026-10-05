"""The command harnesses run to start `cairn serve`."""

import shutil
import sys
from pathlib import Path

# Run via `uvx`/`uv tool run`, cairn lives in uv's cache, which `uv cache clean` deletes.
_EPHEMERAL_MARKERS = ("/uv/cache/", "/.cache/uv/", "/archive-v0/")
UVX_COMMAND = ["uvx", "--from", "cairnmap", "cairn", "serve"]


def is_ephemeral(path: Path) -> bool:
    text = path.as_posix().lower()
    return any(marker in text for marker in _EPHEMERAL_MARKERS)


def server_command() -> list[str]:
    exe = shutil.which("cairn")
    if exe:
        resolved = Path(exe).resolve()
        return list(UVX_COMMAND) if is_ephemeral(resolved) else [str(resolved), "serve"]
    if is_ephemeral(Path(sys.executable)):
        return list(UVX_COMMAND)
    return [sys.executable, "-m", "cairn", "serve"]
