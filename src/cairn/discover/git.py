"""Read git metadata without ever failing a scan."""

import functools
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from cairn.discover.proc import run_text

# A repo's own config can name programs git runs while cairn reads it: core.fsmonitor, hooks
# (post-index-change when `status` refreshes the index) and clean/process filters. A copied or
# downloaded repo must not get to run code, so every call turns those off (spec §20.1).
GIT = (
    "git",
    "--no-optional-locks",
    "-c",
    "core.fsmonitor=false",
    "-c",
    f"core.hooksPath={os.devnull}",
)
_HOST = re.compile(r"[A-Za-z0-9.\-]+(?::\d+)?")
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
    """`host/path` with credentials removed; None for anything unparseable (never raises)."""
    url = _strip_userinfo(url.strip())
    scp = _SCP_LIKE.match(url)
    if scp and "://" not in url:
        host, path = scp.groups()
    else:
        try:
            parsed = urlsplit(url)
            host, path = parsed.hostname or "", parsed.path
        except ValueError:
            return None
    if not host:
        return None
    path = path.strip("/").removesuffix(".git")
    return f"{host}/{path}" if path else host


def _strip_userinfo(url: str) -> str:
    """Drop everything up to the `@` that precedes the host, even when a password holds "/"."""
    scheme, sep, rest = url.partition("://")
    if not sep:
        return url
    for at in reversed([i for i, ch in enumerate(rest) if ch == "@"]):
        userinfo = rest[:at]
        # userinfo has no "/" before a ":" (a password may hold "/"; a path "@v2" isn't one)
        if "/" in userinfo.split(":", 1)[0]:
            continue
        if _HOST.fullmatch(rest[at + 1 :].split("/", 1)[0]):
            return f"{scheme}://{rest[at + 1 :]}"
    return url


def git_command(root: Path) -> list[str]:
    """`git` for read-only calls in `root`, with the repo's own filter drivers neutralised."""
    return [*GIT, *_filter_overrides(root), "-C", str(root)]


def _filter_overrides(root: Path) -> list[str]:
    """Empty clean/smudge/process commands for each filter the repo's own config defines.

    Reading config runs nothing. Only the repo's (local) config is untrusted; filters the user
    set up globally, such as git-lfs, keep working.
    """
    config = root / ".git" / "config"
    try:
        stamp = config.stat().st_mtime_ns
    except OSError:
        return []
    return list(_cached_overrides(str(root), stamp))


@functools.lru_cache(maxsize=1024)
def _cached_overrides(root: str, _stamp: int) -> tuple[str, ...]:
    listing = run_text(
        [
            *GIT,
            "-C",
            root,
            "config",
            "--local",
            "--includes",
            "--name-only",
            "--get-regexp",
            r"^filter\.",
        ],
        timeout=5.0,
        env=git_env(),
    )
    names = {
        key[len("filter.") : key.rindex(".")]
        for key in (listing.stdout.split() if listing else [])
        if key.count(".") >= 2
    }
    return tuple(
        arg
        for name in sorted(names)
        for part in ("clean", "smudge", "process")
        for arg in ("-c", f"filter.{name}.{part}=")
    )


def _git(root: Path, args: list[str], timeout: float) -> str | None:
    result = run_text([*git_command(root), *args], timeout=timeout, env=git_env())
    return result.stdout.strip() if result and result.returncode == 0 else None


def git_text(root: Path, args: list[str], timeout: float = 5.0) -> str | None:
    """Stripped stdout of a read-only git command, or None if it failed."""
    return _git(root, args, timeout)


def git_settings(root: Path, args: list[str], timeout: float = 5.0) -> str | None:
    """`git config` / `rev-parse` as the user would see them (no cairn overrides). These commands
    never touch the work tree, so they run no hooks, filters or fsmonitor."""
    result = run_text(["git", "-C", str(root), *args], timeout=timeout, env=git_env())
    return result.stdout.strip() if result and result.returncode == 0 else None


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
