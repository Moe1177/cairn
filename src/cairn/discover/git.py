"""Read git metadata without ever failing a scan."""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

_SCP_LIKE = re.compile(r"^[\w.-]+@([\w.-]+):(.+)$")


@dataclass(frozen=True)
class GitInfo:
    head_sha: str | None = None
    remote: str | None = None
    dirty: bool | None = None


def git_info(root: Path, timeout: float = 5.0) -> GitInfo:
    head = _git(root, ["rev-parse", "--short", "HEAD"], timeout)
    remote = _git(root, ["config", "--get", "remote.origin.url"], timeout)
    status = _git(root, ["status", "--porcelain", "-uno"], timeout)
    return GitInfo(
        head_sha=head or None,
        remote=normalize_remote(remote) if remote else None,
        dirty=None if status is None else bool(status.strip()),
    )


def normalize_remote(url: str) -> str | None:
    url = url.strip()
    scp = _SCP_LIKE.match(url)
    if scp and "://" not in url:
        host, path = scp.groups()
    else:
        parsed = urlsplit(url)
        host, path = parsed.hostname or "", parsed.path
    if not host:
        return None
    path = path.strip("/").removesuffix(".git")
    return f"{host}/{path}" if path else host


def _git(root: Path, args: list[str], timeout: float) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None
