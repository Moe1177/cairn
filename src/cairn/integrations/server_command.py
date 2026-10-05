"""The command harnesses run to start `cairn serve`."""

import shutil
import sys
from pathlib import Path


def server_command() -> list[str]:
    exe = shutil.which("cairn")
    if exe:
        return [str(Path(exe).resolve()), "serve"]
    return [sys.executable, "-m", "cairn", "serve"]
