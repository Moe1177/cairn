"""A plain git host (any forge, or none), read through git itself: there's no API, so cairn keeps
a clone of each listed repo with its latest commit's folders and no file contents
(`--filter=blob:none --depth=1`: tens to hundreds of KB), lists a tree from it locally, and
fetches the files it reads in one request per repo. `git ls-remote` tells which repos changed.

A host that doesn't support the filter (sourcehut) sends the latest files too; the clone is still
one commit deep. cairn never asks for a login: git's credential helper or ssh key answers, and
never interactively, since a prompt would hang the MCP server.
"""

import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cairn.discover.git import GIT, git_env
from cairn.errors import CairnError
from cairn.remote.host import RepoInfo, SearchPage
from cairn.remote.transport import is_binary, text_of

HEADS_TTL = 300.0  # seconds a repo's tip from ls-remote stays current
TREE_MAX = 300_000  # paths listed per repo
_WORKERS = 16  # ls-remote calls at once: each is one request to the host
_REMOTE_TIMEOUT = 60.0
_CLONE_TIMEOUT = 600.0
_LOCAL_TIMEOUT = 60.0
_STALE = 2 * _CLONE_TIMEOUT  # a lock file this old is a killed git's, not a running one's
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
# Windows paths stop at 260 characters unless Git for Windows is told otherwise.
_LONG_PATHS = ("-c", "core.longpaths=true") if os.name == "nt" else ()
_BRANCH = re.compile(r"^(?!-)(?!.*\.\.)[A-Za-z0-9._/-]{1,255}$")
_SHA = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
# A host busy or limiting requests (gitlab.gnome.org answers 429 past a rate): worth a retry.
_TRANSIENT = re.compile(r"returned error: (?:429|50[234])\b|RPC failed|Connection reset")
_RETRIES = 2
_BACKOFF = 2.0  # seconds before the first retry, doubled for the next
_BUSY = " (the host is limiting requests: try again in a minute)"
_LOGIN = (
    " (log in once with git itself, as with `git ls-remote URL`: cairn uses its credential "
    "helper or ssh key, and never prompts)"
)


def cache_root() -> Path:
    """cairn's cache for this user (clones are shared by every workspace): CAIRN_CACHE_DIR, else
    the platform's cache folder."""
    override = os.environ.get("CAIRN_CACHE_DIR", "").strip()
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Caches")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "cairn"


class GitRepos:
    """The listed repos of one org on a plain git host. Repo names are their paths on the host
    (acme/platform/api); a name not listed is never cloned or read."""

    def __init__(
        self,
        org: str,
        host: str,
        repos: Mapping[str, str],  # full path -> URL, in the order the config lists them
        *,
        cache: Path | None = None,
        protocols: Sequence[str] = ("https", "ssh"),
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.org, self.host = org, host
        self._urls = {name.lower(): (name, url) for name, url in repos.items()}
        self._order = list(repos)
        self._cache = (cache or cache_root()) / "git" / host
        self._git_cmd = (*GIT, *_LONG_PATHS)
        self._env = _quiet_env(protocols)
        self._clock, self._sleep = clock, sleep
        self._heads: dict[str, tuple[str, str, float]] = {}  # name -> (branch, tip, when)
        self._unreachable: dict[str, str] = {}  # name -> why ls-remote failed
        self._trees: dict[str, tuple[str, dict[str, str]]] = {}  # name -> (tip, path -> blob)
        self._ready: set[str] = set()  # clones whose origin URL was checked this process
        self._promisor: dict[str, bool] = {}  # clones the host filtered (blobs come on demand)
        self._fetched: set[tuple[str, str]] = set()  # (name, blob) known to be in its clone
        self._locks: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(_WORKERS, thread_name_prefix="cairn-git")

    def search_code(self, query: str, *, per_page: int = 10) -> SearchPage:
        raise CairnError(self._no_search())

    def search_repos(self, query: str, *, per_page: int = 10) -> tuple[tuple[str, ...], float]:
        raise CairnError(self._no_search())

    def file_exists(self, repo: str, path: str) -> bool:
        return path.strip("/") in self._tree_of(repo)[1]

    def read_file(self, repo: str, path: str, *, max_bytes: int = 200_000) -> str | None:
        """A file's text at the tip of `repo`'s default branch: None when it isn't there (a
        folder isn't a file), is binary, or is longer than `max_bytes`."""
        oid = self._tree_of(repo)[1].get(path.strip("/"))
        if oid is None:
            return None
        key = self._known(repo)
        with self._repo_lock(key):  # a missing blob is fetched into the clone
            body = self._git(
                ["cat-file", "blob", oid], cwd=self._clone_dir(key), what=f"read {path}"
            )
        self._fetched.add((key, oid))
        if len(body) > max_bytes or is_binary(body):
            return None
        return text_of(body)

    def prefetch(self, repo: str, paths: Sequence[str]) -> None:
        """Fetch the files about to be read in one request, rather than one each. Best effort:
        if it fails, each read fetches its own file and reports its own error."""
        try:
            self._prefetch(repo, paths)
        except CairnError:
            return

    def list_repos(self, owner: str, *, page: int = 1, per_page: int = 100) -> tuple[RepoInfo, ...]:
        """One page of the listed repos, in the config's order, each with its default branch
        and tip (as `pushed`: what changed is all cairn compares it for). A repo git can't
        reach is kept with neither, and its tree then says why; if none on the first page can
        be reached (the host is down, or git has no login for it), the listing fails with
        git's reason."""
        if owner.lower() != self.org.lower():
            return ()
        size = max(1, min(per_page, 100))
        names = self._order[(page - 1) * size : page * size]
        heads = list(self._pool.map(self._head_or_none, names))
        if page == 1 and names and all(head is None for head in heads):
            why = self._unreachable.get(names[0].lower(), f"git couldn't reach {names[0]}")
            raise CairnError(why)
        return tuple(
            RepoInfo(name=name, default_branch=head[0], pushed=head[1])
            if head
            else RepoInfo(name=name, default_branch="")
            for name, head in zip(names, heads, strict=True)
        )

    def tree(self, repo: str, ref: str) -> tuple[tuple[str, ...], bool]:
        """Every file path at the tip of the default branch (`ref` names it; an empty repo has
        none), and whether the list was cut short (over TREE_MAX paths)."""
        key = self._known(repo)
        if not ref:
            why = self._unreachable.get(key)
            if why is not None:
                raise CairnError(why)
            return (), False
        files = self._tree_of(repo)[1]
        return tuple(files)[:TREE_MAX], len(files) > TREE_MAX

    def remaining(self, resource: str = "core") -> int | None:
        return None  # git has no rate limit to report

    def _no_search(self) -> str:
        return (
            f"{self.org} is a list of plain git repos, which have no code search: find_similar "
            "and search_org work on GitHub and GitLab orgs. read_org_file and org_packages read these repos."
        )

    def _known(self, repo: str) -> str:
        key = repo.strip().strip("/").lower()
        if key not in self._urls:
            raise CairnError(f"{repo.strip()!r} isn't one of the repos {self.org} lists")
        return key

    def _repo_lock(self, key: str) -> threading.Lock:
        with self._lock:
            return self._locks.setdefault(key, threading.Lock())

    def _clone_dir(self, key: str) -> Path:
        """One flat folder per repo, its name bounded: a group's subgroups would otherwise nest
        it past what Windows allows a path."""
        digest = hashlib.sha256(key.encode()).hexdigest()[:16]
        return self._cache / f"{key.rsplit('/', 1)[-1][:40]}-{digest}.git"

    def _prefetch(self, repo: str, paths: Sequence[str]) -> None:
        key = self._known(repo)
        files = self._tree_of(repo)[1]
        wanted = {files[p] for p in paths if p in files}
        wanted -= {oid for name, oid in self._fetched if name == key}
        if not wanted or not self._promisor.get(key):
            return  # nothing new, or the host sent every file with the clone
        with self._repo_lock(key):  # what the clone has: listed locally, never fetched
            local = self._git(
                ["cat-file", "--batch-check=%(objectname)", "--batch-all-objects", "--unordered"],
                cwd=self._clone_dir(key),
                check=False,
            )
        present = wanted.intersection(local.decode("ascii", errors="replace").split())
        self._fetched.update((key, oid) for oid in present)
        oids = sorted(wanted - present)
        if not oids:
            return
        fetch = ["-c", "fetch.negotiationAlgorithm=noop", "fetch", "-q", "--no-tags"]
        fetch += ["--no-write-fetch-head", "--recurse-submodules=no", "--filter=blob:none"]
        with self._repo_lock(key):
            self._git(
                [*fetch, "--stdin", "origin"],
                cwd=self._clone_dir(key),
                stdin="".join(f"{oid}\n" for oid in oids).encode(),
                timeout=_REMOTE_TIMEOUT,
                what=f"fetch {repo}'s files",
            )
        self._fetched.update((key, oid) for oid in oids)

    def _head_or_none(self, name: str) -> tuple[str, str] | None:
        try:
            return self._head(name)
        except CairnError as exc:
            with self._lock:
                self._unreachable[name.lower()] = str(exc)
            return None

    def _head(self, name: str) -> tuple[str, str]:
        """(default branch, tip) from ls-remote, kept HEADS_TTL; ("", "") for an empty repo."""
        key = self._known(name)
        with self._lock:
            known = self._heads.get(key)
        if known is not None and self._clock() - known[2] < HEADS_TTL:
            return known[0], known[1]
        shown, url = self._urls[key]
        out = self._git(
            ["ls-remote", "--symref", url, "HEAD"],
            timeout=_REMOTE_TIMEOUT,
            what=f"reach {shown}",
            hint=_LOGIN,
        )
        branch, tip = _parse_head(out.decode("utf-8", errors="replace"))
        if not tip and self._git(
            ["ls-remote", "--heads", url], timeout=_REMOTE_TIMEOUT, what=f"reach {shown}"
        ):  # it has branches, but HEAD names none of them: not an empty repo
            raise CairnError(
                f"{shown}'s HEAD names no branch it has: point it at the default branch on the host"
            )
        with self._lock:
            self._heads[key] = (branch, tip, self._clock())
            self._unreachable.pop(key, None)
        return branch, tip

    def _tree_of(self, repo: str) -> tuple[str, dict[str, str]]:
        """(tip ls-remote gave, path -> blob id) of the default branch, cloning or fetching it
        first. Kept by that tip: a push landing during the fetch is read next time."""
        key = self._known(repo)
        branch, tip = self._head(repo)
        with self._repo_lock(key):
            known = self._trees.get(key)
            if known is not None and known[0] == tip:
                return known
            if not tip:
                return tip, {}
            have = self._sync(key, branch, tip)
            listing = self._git(
                ["ls-tree", "-r", "-z", "--full-tree", have],
                cwd=self._clone_dir(key),
                what=f"list {self._urls[key][0]}",
            )
            files = _blobs(listing.decode("utf-8", errors="replace"))
            self._trees[key] = (tip, files)
            return tip, files

    def _sync(self, key: str, branch: str, tip: str) -> str:
        """Clone the repo, or fetch its new tip; the tip the clone now has."""
        name, url = self._urls[key]
        where = self._clone_dir(key)
        if branch != "HEAD" and not _BRANCH.fullmatch(branch):
            raise CairnError(f"{name}'s default branch {branch!r} isn't a name cairn reads")
        local = f"refs/heads/{branch}" if branch != "HEAD" else "refs/cairn/head"
        if not where.exists():
            self._clone(name, url, branch, where)
        elif key not in self._ready:
            self._git(["remote", "set-url", "origin", url], cwd=where, what=f"update {name}")
        self._ready.add(key)
        have = self._ref(where, local)
        if have != tip:
            source = f"refs/heads/{branch}" if branch != "HEAD" else "HEAD"
            fetch = ["fetch", "-q", "--filter=blob:none", "--depth=1", "--no-tags", "origin"]
            fetch.append(f"+{source}:{local}")
            try:
                self._fetch(fetch, where, name)
            except CairnError as exc:
                if "lock" not in str(exc) or not _clear_stale_locks(where):
                    raise
                self._fetch(fetch, where, name)  # a killed git's lock was in the way
            have = self._ref(where, local)
        if key not in self._promisor:
            promisor = self._git(
                ["config", "--get", "remote.origin.promisor"], cwd=where, check=False
            )
            self._promisor[key] = promisor.strip() == b"true"
        if not have:
            raise CairnError(f"git couldn't fetch {name}'s {branch} branch")
        return have

    def _fetch(self, args: list[str], where: Path, name: str) -> None:
        self._git(args, cwd=where, timeout=_CLONE_TIMEOUT, what=f"fetch {name}", hint=_LOGIN)

    def _clone(self, name: str, url: str, branch: str, where: Path) -> None:
        try:
            where.parent.mkdir(parents=True, exist_ok=True)
            temp = Path(tempfile.mkdtemp(prefix=".clone-", dir=where.parent))
        except OSError as exc:
            raise CairnError(f"couldn't make a folder in cairn's cache for {name}: {exc}") from exc
        try:
            only = ["--branch", branch] if branch != "HEAD" else []
            self._git(
                ["clone", "-q", "--bare", "--filter=blob:none", "--depth=1", "--no-tags"]
                + ["--single-branch", *only, "--", url, str(temp)],
                timeout=_CLONE_TIMEOUT,
                what=f"clone {name}",
                hint=_LOGIN,
            )
            if branch == "HEAD":  # no default branch named: keep the tip under cairn's own ref
                self._git(["update-ref", "refs/cairn/head", "HEAD"], cwd=temp, what=f"clone {name}")
            try:
                temp.replace(where)
            except OSError as exc:
                if not where.exists():  # not just another process cloning it first
                    raise CairnError(f"couldn't keep the clone of {name}: {exc}") from exc
        finally:
            _remove_tree(temp)

    def _ref(self, where: Path, ref: str) -> str:
        out = self._git(["rev-parse", "--verify", "-q", ref], cwd=where, check=False)
        found = out.decode("ascii", errors="replace").strip()
        return found if _SHA.fullmatch(found) else ""

    def _git(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        stdin: bytes | None = None,
        timeout: float = _LOCAL_TIMEOUT,
        what: str = "",
        hint: str = "",
        check: bool = True,
    ) -> bytes:
        """git's stdout, retrying a busy host. Its stdin is never inherited: an MCP server's is
        the protocol."""
        done = self._run(args, cwd=cwd, stdin=stdin, timeout=timeout, what=what)
        reason = done.stderr.decode("utf-8", errors="replace")
        for attempt in range(_RETRIES):
            if done.returncode == 0 or not _TRANSIENT.search(reason):
                break
            self._sleep(_BACKOFF * 2**attempt)
            done = self._run(args, cwd=cwd, stdin=stdin, timeout=timeout, what=what)
            reason = done.stderr.decode("utf-8", errors="replace")
        if done.returncode != 0 and check:
            hint = _BUSY if "error: 429" in reason else hint
            raise CairnError(f"git couldn't {what}: {_reason(reason)}{hint}")
        return done.stdout if done.returncode == 0 else b""

    def _run(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None,
        stdin: bytes | None,
        timeout: float,
        what: str,
    ) -> subprocess.CompletedProcess[bytes]:
        source = {"input": stdin} if stdin is not None else {"stdin": subprocess.DEVNULL}
        try:
            return subprocess.run(
                [*self._git_cmd, *args],
                cwd=cwd,
                capture_output=True,
                timeout=timeout,
                env=self._env,
                check=False,
                creationflags=_NO_WINDOW,
                start_new_session=os.name != "nt",  # no terminal for ssh to prompt on
                **source,  # type: ignore[arg-type]
            )
        except subprocess.TimeoutExpired as exc:
            raise CairnError(f"git took over {timeout:.0f} s to {what}") from exc
        except OSError as exc:
            raise CairnError(f"couldn't run git, which reads plain git hosts: {exc}") from exc


def _quiet_env(protocols: Sequence[str]) -> dict[str, str]:
    """git's environment: only these transports, whatever a URL or any git config says (no
    file://, no ext::), and nothing that could prompt for a login or open a window."""
    env = {k: v for k, v in git_env().items() if k not in ("GIT_ASKPASS", "SSH_ASKPASS")}
    env.update(
        GIT_ALLOW_PROTOCOL=":".join(protocols),
        GIT_TERMINAL_PROMPT="0",
        GCM_INTERACTIVE="never",  # Git Credential Manager would open a window
    )
    if "GIT_SSH_COMMAND" not in env and not _ssh_configured(env):
        env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes"  # no passphrase or host key prompt
    return env


def _ssh_configured(env: Mapping[str, str]) -> bool:
    """Whether the user's git config names its own ssh program (theirs is kept)."""
    try:
        done = subprocess.run(
            [*GIT, "config", "--get", "core.sshCommand"],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            env=dict(env),
            timeout=_LOCAL_TIMEOUT,
            check=False,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(done.stdout.strip())


def _clear_stale_locks(where: Path) -> bool:
    """Remove the lock files a killed git left in a clone; whether there were any."""
    now = time.time()
    found = False
    for lock in [*where.glob("*.lock"), *where.glob("refs/**/*.lock")]:
        try:
            if now - lock.stat().st_mtime > _STALE:
                lock.unlink()
                found = True
        except OSError:
            continue
    return found


def _remove_tree(path: Path) -> None:
    """Delete a folder git wrote, read-only pack files too (Windows won't delete those)."""

    def writable(_function: object, name: str, _error: object) -> None:
        try:
            os.chmod(name, stat.S_IWRITE)
            os.unlink(name)
        except OSError:
            pass

    if path.exists():
        shutil.rmtree(path, onerror=writable)  # onexc, its successor, needs Python 3.12


def _parse_head(out: str) -> tuple[str, str]:
    """(default branch, tip) from `ls-remote --symref URL HEAD`; the branch is "HEAD" when the
    host doesn't name it, and both are "" for an empty repo."""
    branch = tip = ""
    for line in out.splitlines():
        first, _, ref = line.partition("\t")
        if ref != "HEAD":
            continue
        if first.startswith("ref: refs/heads/"):
            branch = first.removeprefix("ref: refs/heads/")
        elif _SHA.fullmatch(first):
            tip = first
    return (branch or "HEAD", tip) if tip else ("", "")


def _blobs(listing: str) -> dict[str, str]:
    """path -> blob id from `ls-tree -r -z`: files and symlinks, not submodules."""
    files: dict[str, str] = {}
    for entry in listing.split("\0"):
        meta, _, path = entry.partition("\t")
        parts = meta.split(" ")
        if len(parts) == 3 and parts[1] == "blob" and path:
            files[path] = parts[2]
    return files


def _reason(stderr: str) -> str:
    """git's reason: its first fatal line (what follows only explains it), else its last."""
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    fatal = [line for line in lines if line.startswith("fatal:")]
    return (fatal or lines[-1:] or ["no reason given"])[0][:300]
