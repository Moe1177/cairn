"""The command harnesses (and git hooks) run to start cairn (spec §20.2).

It must keep working from any folder and from GUI apps with a minimal PATH, so it prefers an
absolute path to the install that is running now. The last element is always "serve"; hooks
swap it for "refresh".
"""

import os
import shutil
import sys
from pathlib import Path

import cairn

# Run via `uvx`/`uv tool run`, cairn lives in uv's cache, which `uv cache clean` deletes.
_EPHEMERAL_MARKERS = ("/uv/cache/", "/.cache/uv/", "/archive-v0/")
# Version-manager shims choose the Python from the current folder, so they break elsewhere.
_SHIM_MARKERS = ("/shims/",)
UVX_COMMAND = ["uvx", "--from", f"cairnmap=={cairn.__version__}", "cairn", "serve"]


def _posix(path: Path | str) -> str:
    return str(path).replace("\\", "/").lower()


def is_ephemeral(path: Path) -> bool:
    text = _posix(path)
    return any(marker in text for marker in _EPHEMERAL_MARKERS)


def _usable(path: Path) -> bool:
    text = _posix(path)
    return not is_ephemeral(path) and not any(marker in text for marker in _SHIM_MARKERS)


def server_command() -> list[str]:
    python = Path(sys.executable)
    beside = python.parent / ("cairn.exe" if os.name == "nt" else "cairn")
    if _usable(python) and beside.is_file():
        return [str(beside), "serve"]
    found = shutil.which("cairn")
    if found and _usable(Path(found)):
        resolved = Path(found).resolve()
        if _usable(resolved):
            return [str(resolved), "serve"]
    if _usable(python):
        return [str(python), "-m", "cairn", "serve"]
    return [shutil.which("uvx") or "uvx", *UVX_COMMAND[1:]]
