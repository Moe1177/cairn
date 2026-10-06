"""`cairn doctor`: check the environment cairn depends on and say what to fix (spec §22)."""

import contextlib
import platform
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from cairn import providers
from cairn.discover.git import git_refused
from cairn.discover.proc import run_text
from cairn.errors import CairnError
from cairn.integrations.harnesses import installed_harnesses
from cairn.paths import cairn_dir
from cairn.providers.meta import indexed_repos
from cairn.store.workspace_store import load_workspace

OK, WARN, FAIL, INFO = "OK", "WARN", "FAIL", "INFO"
_MIN_PYTHON = (3, 11)


@dataclass(frozen=True)
class Check:
    status: str
    name: str
    detail: str

    def line(self) -> str:
        return f"{self.status:<4} {self.name}: {self.detail}"


def run_checks(root: Path) -> list[Check]:
    return [
        _python(),
        _git(),
        *_map(root),
        _writable(root),
        _harnesses(root),
        *_git_trust(root),
        *_graphify(root),
    ]


def _python() -> Check:
    version = platform.python_version()
    where = f"{version} on {platform.platform()}"
    if sys.version_info[:2] < _MIN_PYTHON:
        return Check(FAIL, "python", f"{where}; cairn needs 3.11 or newer")
    return Check(OK, "python", where)


def _git() -> Check:
    git = shutil.which("git")
    if git is None:
        return Check(
            FAIL,
            "git",
            "not on PATH: install git (https://git-scm.com); without it there are no "
            "remotes, HEADs, staleness checks or scan cache",
        )
    done = run_text([git, "--version"], timeout=10)
    if not done or done.returncode != 0:
        return Check(WARN, "git", f"{git} didn't report a version; is it a working git?")
    return Check(OK, "git", done.stdout.strip())


def _map(root: Path) -> list[Check]:
    try:
        workspace = load_workspace(root)
    except (CairnError, OSError, ValueError) as exc:  # ValueError: not UTF-8 / not JSON
        detail = type(exc).__name__ if isinstance(exc, ValueError) else str(exc)
        return [Check(FAIL, "map", f"unreadable ({detail}); run `cairn scan --full`")]
    if workspace is None:
        return [Check(WARN, "map", f"none in {root}; run `cairn scan` from the folder of repos")]
    errors = sum(len(r.detector_errors) for r in workspace.repos)
    checks = [
        Check(
            OK,
            "map",
            f"{len(workspace.repos)} repos, {len(workspace.edges)} links, "
            f"generated {workspace.generated_at}",
        )
    ]
    if errors:
        checks.append(Check(WARN, "detectors", f"{errors} errors; see `cairn status`"))
    return checks


def _writable(root: Path) -> Check:
    target = cairn_dir(root) if cairn_dir(root).is_dir() else root
    try:
        with tempfile.NamedTemporaryFile(dir=target, prefix=".cairn-doctor-"):
            pass
    except OSError as exc:
        return Check(FAIL, "write access", f"can't write to {target}: {exc.strerror or exc}")
    return Check(OK, "write access", str(target))


def _git_trust(root: Path) -> list[Check]:
    workspace = None
    with contextlib.suppress(CairnError, OSError, ValueError):
        workspace = load_workspace(root)
    if workspace is None:
        return []
    refused = [root / r.path for r in workspace.repos if git_refused(root / r.path)]
    if not refused:
        return [Check(OK, "git trust", "git reads every repo")]
    commands = "; ".join(
        f"git config --global --add safe.directory {p.as_posix()}" for p in refused
    )
    return [
        Check(
            WARN,
            "git trust",
            f"{len(refused)} repo(s) owned by another user, so git won't read them. Run: {commands}",
        )
    ]


def _harnesses(root: Path) -> Check:
    names = installed_harnesses(root)
    if not names:
        return Check(WARN, "harnesses", "none; run `cairn install claude` (or codex, gemini, all)")
    return Check(OK, "harnesses", ", ".join(names))


def _graphify(root: Path) -> list[Check]:
    provider = providers.default_provider()
    if not provider.available():
        return [
            Check(INFO, "graphify", "not installed (optional: pip install 'cairnmap[graphify]')")
        ]
    checks = [Check(OK, "graphify", provider.version() or "version unknown")]
    workspace = None
    with contextlib.suppress(CairnError, OSError, ValueError):  # _map() reported it already
        workspace = load_workspace(root)
    stale = []
    for repo_id in indexed_repos(root):
        repo = workspace.repo(repo_id) if workspace else None
        if repo is not None and provider.status(root, repo_id, root / repo.path).stale:
            stale.append(repo_id)
    if stale:
        checks.append(
            Check(WARN, "deep indexes", f"stale: {', '.join(stale)}; run `cairn refresh --deep`")
        )
    return checks
