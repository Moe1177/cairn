"""Read git metadata without ever failing a scan."""

import hashlib
import os
import re
from collections.abc import Iterable
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
    head = head_sha(root, timeout)
    remote = git_remote(root, timeout)
    status = _git(root, ["status", "--porcelain", "-uno"], timeout)
    return GitInfo(
        head_sha=head or None,
        remote=remote,
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
    config = _local_config(root)
    return list(config.overrides) if config else []


def git_remote(root: Path, timeout: float = 5.0) -> str | None:
    """`remote.origin.url` normalised to `host/path`: credentials never leave this function,
    so nothing remembered or shown can hold them."""
    config = _local_config(root)
    if config is not None and config.listed:
        return config.remote
    raw = _git(root, ["config", "--get", "remote.origin.url"], timeout)
    return normalize_remote(raw) if raw else None


@dataclass(frozen=True)
class _LocalConfig:
    overrides: tuple[str, ...]
    remote: str | None
    listed: bool  # False when git couldn't list its config (git < 2.26): ask per key instead


# Answers that only change when files under .git/ change, keyed by (repo, stamp of those
# files) and shared by worker threads. Only HEAD shas and normalised remotes are persisted
# between runs (git-memo.json). Filter overrides are never taken from disk: a memo file can't
# be trusted to say a repo has no filters, so a config that mentions one is always asked.
_CONFIGS: dict[tuple[str, str], _LocalConfig] = {}  # this process only
_REMOTES: dict[tuple[str, str], str | None] = {}
_HEADS: dict[tuple[str, str], str] = {}
_MEMO_MAX = 4096
_IN_PROCESS = "mtime:"
_STAMP_READ_MAX = 1_000_000
_SHA = re.compile(r"[0-9a-f]{4,64}")
# What normalize_remote() returns: host[/path], no scheme, no credentials, no spaces.
_NORMALISED_REMOTE = re.compile(r"[A-Za-z0-9.-]{1,253}(?:/[^\s@:]{1,500})?")


def forget_git_memo() -> None:
    _CONFIGS.clear()
    _REMOTES.clear()
    _HEADS.clear()


def export_git_memo(roots: Iterable[Path]) -> dict[str, dict]:
    """The remembered HEADs and remotes for `roots`, as JSON-ready data."""
    wanted = {str(root) for root in roots}
    out: dict[str, dict] = {}
    for (root, stamp), remote in list(_REMOTES.items()):
        if root in wanted and not stamp.startswith(_IN_PROCESS):
            out.setdefault(root, {})["remote"] = [stamp, remote]
    for (root, stamp), sha in list(_HEADS.items()):
        if root in wanted:
            out.setdefault(root, {})["head"] = [stamp, sha]
    return out


def import_git_memo(data: object) -> None:
    """Load what export_git_memo() wrote. Anything malformed is ignored, never trusted."""
    if not isinstance(data, dict):
        return
    for root, entry in list(data.items())[:_MEMO_MAX]:
        if not isinstance(root, str) or not isinstance(entry, dict):
            continue
        remote, head = entry.get("remote"), entry.get("head")
        if (
            isinstance(remote, list)
            and len(remote) == 2
            and isinstance(remote[0], str)
            and (remote[1] is None or _NORMALISED_REMOTE.fullmatch(str(remote[1])))
        ):
            _REMOTES[(root, remote[0])] = remote[1]
        if (
            isinstance(head, list)
            and len(head) == 2
            and all(isinstance(x, str) for x in head)
            and _SHA.fullmatch(head[1])
        ):
            _HEADS[(root, head[0])] = head[1]


def _remember(memo: dict, key: tuple[str, str], value: object) -> None:
    if len(memo) >= _MEMO_MAX:
        memo.clear()
    memo[key] = value


def _config_bytes(root: Path) -> bytes | None:
    """.git/config when a hash of it alone decides the answer: no includes, no per-worktree
    config, not oversized. None otherwise (or when there's no such file)."""
    git = root / ".git"
    try:
        data = (git / "config").read_bytes()[: _STAMP_READ_MAX + 1]
    except OSError:
        return None
    lowered = data.lower()
    if (
        len(data) > _STAMP_READ_MAX
        or b"[include" in lowered
        or b"worktreeconfig" in lowered
        or (git / "config.worktree").exists()
    ):
        return None
    return data


def config_stamp(root: Path) -> str | None:
    data = _config_bytes(root)
    return None if data is None else hashlib.sha1(data).hexdigest()


def head_stamp(root: Path) -> str | None:
    """A hash of what decides HEAD's commit, or None for layouts it can't vouch for: a `.git`
    file (worktrees, submodules), the reftable backend, a symbolic ref chain, an unusual ref."""
    git = root / ".git"
    try:
        if not git.is_dir() or (git / "reftable").exists():
            return None
        head = (git / "HEAD").read_bytes()[:512]
        parts = [head]
        if head.startswith(b"ref: "):
            ref = head[5:].strip().decode("ascii")
            if not re.fullmatch(r"refs/[A-Za-z0-9._/-]{1,200}", ref) or ".." in ref:
                return None
            try:
                target = (git / ref).read_bytes()[:512]
            except FileNotFoundError:
                target = b"-"
            if target.startswith(b"ref:"):
                return None  # HEAD -> alias -> branch: the branch's moves wouldn't show here
            parts.append(target)
            try:
                packed = (git / "packed-refs").stat()
                parts.append(f"{packed.st_mtime_ns}:{packed.st_size}".encode())
            except FileNotFoundError:
                parts.append(b"-")
    except (OSError, UnicodeDecodeError):
        return None
    return hashlib.sha1(b"\0".join(parts)).hexdigest()


def head_sha(root: Path, timeout: float = 5.0) -> str | None:
    """`git rev-parse --short HEAD`, remembered until HEAD or its ref changes."""
    stamp = head_stamp(root)
    key = (str(root), stamp or "")
    if stamp is not None:
        found = _HEADS.get(key)
        if found is not None:
            return found
    sha = _git(root, ["rev-parse", "--short", "HEAD"], timeout) or None
    if stamp is not None and sha:
        _remember(_HEADS, key, sha)
    return sha


def _local_config(root: Path) -> _LocalConfig | None:
    data = _config_bytes(root)
    if data is None:
        try:
            mtime = (root / ".git" / "config").stat().st_mtime_ns
        except OSError:
            return None
        stamp = f"{_IN_PROCESS}{mtime}"  # includes, worktree config: this process only
    else:
        stamp = hashlib.sha1(data).hexdigest()
    key = (str(root), stamp)
    found = _CONFIGS.get(key)
    if found is not None:
        return found
    # A remembered remote may stand in for git only when this exact config defines no filter:
    # then there is nothing to neutralise, whatever the memo file says.
    if data is not None and b"filter" not in data.lower() and key in _REMOTES:
        found = _LocalConfig((), _REMOTES.get(key), listed=True)
    else:
        found = _read_config(str(root))
    _remember(_CONFIGS, key, found)
    if found.listed:
        _remember(_REMOTES, key, found.remote)
    return found


def _read_config(root: str) -> _LocalConfig:
    """One `git config --list` for both the filter overrides and the origin remote."""
    listing = run_text(
        [*GIT, "-C", root, "config", "-z", "--list", "--show-scope"],
        timeout=5.0,
        env=git_env(),
    )
    if listing is None or listing.returncode != 0:
        return _LocalConfig(_listed_overrides(root), None, listed=False)
    names: set[str] = set()
    remote = None
    parts = listing.stdout.split("\0")
    for scope, entry in zip(parts[0::2], parts[1::2], strict=False):
        key, _, value = entry.partition("\n")
        lowered = key.lower()
        # Only the repo's own config is untrusted; global filters (git-lfs) keep working.
        if scope in ("local", "worktree") and lowered.startswith("filter.") and key.count(".") >= 2:
            names.add(key[len("filter.") : key.rindex(".")])
        if lowered == "remote.origin.url":
            remote = normalize_remote(value) if value else None  # later scopes win
    return _LocalConfig(_override_args(names), remote, listed=True)


def _override_args(names: set[str]) -> tuple[str, ...]:
    return tuple(
        arg
        for name in sorted(names)
        for part in ("clean", "smudge", "process")
        for arg in ("-c", f"filter.{name}.{part}=")
    )


def _listed_overrides(root: str) -> tuple[str, ...]:
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
    return _override_args(names)


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
