"""Read git metadata without ever failing a scan."""

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

_SCP_LIKE = re.compile(r"^[\w.-]+@([\w.-]+):(.+)$")
_SHA = re.compile(r"[0-9a-fA-F]{4,64}")
# Git exports these to hooks; inherited by a hook-started refresh they would point
# every `git -C <other repo>` call at the repo that ran the hook.
_REPO_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX", "GIT_COMMON_DIR")


def git_env() -> dict[str, str]:
    """Environment for cairn's read-only git calls: no inherited repo, no optional locks.

    Without GIT_OPTIONAL_LOCKS=0, `git status` may rewrite the index and collide with a
    rebase or merge that triggered the hook.
    """
    env = {k: v for k, v in os.environ.items() if k not in _REPO_ENV}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return env


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
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=git_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (result.stdout or "").strip() if result.returncode == 0 else None


def summary_is_stale(root: Path, since: str, threshold: int, timeout: float = 10.0) -> bool:
    """Spec §18: stale when manifests or top-level entries changed, or > threshold files changed."""
    from cairn.discover.repos import MANIFEST_NAMES

    if not _SHA.fullmatch(since):
        return True  # not a commit id (hand-edited file): never pass it to git
    changed = _git(root, ["diff", "--name-only", since, "HEAD"], timeout)
    if changed is None:
        return True  # sha unknown here (rebased away, shallow clone): be safe
    files = [f for f in changed.splitlines() if f.strip()]
    if len(files) > threshold or any(Path(f).name in MANIFEST_NAMES for f in files):
        return True
    before = _git(root, ["ls-tree", "--name-only", since], timeout)
    after = _git(root, ["ls-tree", "--name-only", "HEAD"], timeout)
    return before is None or after is None or set(before.split()) != set(after.split())
