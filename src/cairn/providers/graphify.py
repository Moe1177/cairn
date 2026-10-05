"""The graphify provider (spec §23): builds a per-repo code graph by running graphify.

graphify runs as a subprocess, never imported. The build is always code-only (no LLM, no
network) and writes to `<ws>/.cairn/deep/<repo>/graphify-out/`, never into the repo. It runs
with an allowlisted environment, so no API key or token can reach it.
"""

import json
import os
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from cairn.discover.git import git_info
from cairn.discover.proc import run_text
from cairn.providers.base import BuildResult, DeepStatus
from cairn.providers.graph import hubs, load_graph
from cairn.providers.meta import META_FILE, deep_dir, read_deep_meta
from cairn.scan_cache import worktree_fingerprint
from cairn.store.atomic import atomic_write_text

INSTALL_HINT = "install it with `pip install 'cairnmap[graphify]'` (or `uv tool install graphifyy`)"
_VERSION = re.compile(r"\d+\.\d+\.\d+")
# Only what a program needs to run. Everything else (API keys, tokens, *_BASE_URL) stays out.
_ENV_ALLOWLIST = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "COMSPEC",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "TEMP",
    "TMP",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
)


class GraphifyProvider:
    id = "graphify"

    def __init__(self, executable: str | None = None, extra_env: dict[str, str] | None = None):
        self.executable = executable or _find_executable()
        self._extra_env = dict(extra_env or {})

    def available(self) -> bool:
        return bool(self.executable) and (
            Path(self.executable).is_file() or shutil.which(self.executable) is not None
        )

    def graph_path(self, ws_root: Path, repo_id: str) -> Path:
        return deep_dir(ws_root, repo_id) / "graphify-out" / "graph.json"

    def version(self) -> str | None:
        if not self.available() or self.executable is None:
            return None
        done = run_text([self.executable, "--version"], timeout=30, env=self._env())
        found = _VERSION.search(done.stdout + done.stderr) if done else None
        return found.group(0) if found else None

    def build(self, ws_root: Path, repo_id: str, repo_root: Path, *, timeout: float) -> BuildResult:
        if not self.available() or self.executable is None:
            return BuildResult(False, f"graphify isn't installed: {INSTALL_HINT}")
        out = deep_dir(ws_root, repo_id)
        out.mkdir(parents=True, exist_ok=True)
        command = [self.executable, "extract", str(repo_root), "--code-only", "--out", str(out)]
        done = run_text(command, cwd=out, timeout=timeout, env=self._env())
        if done is None:
            return BuildResult(
                False, f"graphify timed out after {timeout:.0f}s (or couldn't start)"
            )
        graph = load_graph(self.graph_path(ws_root, repo_id))
        if done.returncode != 0 or graph is None:
            detail = (done.stderr or done.stdout).strip().splitlines()[-1:] or ["no graph written"]
            return BuildResult(False, f"graphify failed for {repo_id}: {detail[0][:300]}")
        meta = {
            "provider": self.id,
            "version": self.version(),
            "head_sha": git_info(repo_root).head_sha,
            "fingerprint": worktree_fingerprint(repo_root),
            "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "nodes": len(graph.nodes),
            "hubs": hubs(graph, 5),
        }
        atomic_write_text(out / META_FILE, json.dumps(meta, indent=2) + "\n")
        return BuildResult(True, f"{repo_id}: {len(graph.nodes)} symbols indexed")

    def status(self, ws_root: Path, repo_id: str, repo_root: Path) -> DeepStatus:
        meta = read_deep_meta(ws_root, repo_id)
        if meta is None or not self.graph_path(ws_root, repo_id).is_file():
            return DeepStatus(provider=self.id)
        stale = (
            git_info(repo_root).head_sha != meta.head_sha
            or worktree_fingerprint(repo_root) != meta.fingerprint
        )
        return DeepStatus(
            provider=self.id,
            present=True,
            stale=stale,
            built_sha=meta.head_sha,
            built_at=meta.built_at,
            version=meta.version,
            nodes=meta.nodes,
        )

    def _env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k.upper() in _ENV_ALLOWLIST}
        env.update(GRAPHIFY_QUERY_LOG_DISABLE="1", PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        env.update(self._extra_env)
        return env


def _find_executable() -> str | None:
    """The graphify installed beside the running cairn (the `graphify` extra), else PATH."""
    beside = Path(sys.executable).parent / ("graphify.exe" if os.name == "nt" else "graphify")
    if beside.is_file():
        return str(beside)
    return shutil.which("graphify")
