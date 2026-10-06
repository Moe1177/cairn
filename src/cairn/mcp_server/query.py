"""The MCP `query` tool: where in the code a question is answered.

Grep first, the code graph as a backstop (see cairn.locate.hybrid for the measurements behind
that order). Searches the repo asked about and any other repo the question names; when those
have nothing, the repos the map relates to it. Says which locator answered and why.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cairn import providers
from cairn.discover.git import head_sha
from cairn.locate.hybrid import hybrid_locate
from cairn.locate.model import LocateHit, LocateResult
from cairn.locate.workspace import fan_out, scoped_locate
from cairn.model.graph import Repo, Workspace
from cairn.providers.graph import Graph, load_graph_cached
from cairn.providers.graphify import GraphifyProvider
from cairn.providers.meta import read_deep_meta
from cairn.security.text import clean_inline

HITS = 10
_WORKERS = 8
# Agents ask in bursts. Checking a deep index for staleness runs `git status`, so a verdict is
# reused for a few seconds per (repo, HEAD, build): an edit shows up on the next query after that.
STALE_TTL = 5.0
_STALE: dict[tuple[str, str | None, str | None], tuple[float, bool]] = {}
_STALE_LOCK = threading.Lock()


def answer(
    ws_root: Path, workspace: Workspace, repo: Repo, question: str
) -> tuple[str, list[str], list[str]]:
    """(header, hit lines, notes) for `question` asked about `repo`."""
    results, named_ids, related_ids = scoped_locate(
        workspace, repo.id, question, lambda ids: _locate(ws_root, _repos(workspace, ids), question)
    )
    named = _repos(workspace, named_ids)
    related = _repos(workspace, related_ids)
    notes = _incomplete(ws_root, [repo, *named, *related])
    if any(result.partial for result in results.values()):
        notes.append("(a search stopped early at its time or size limit: ask a narrower question)")
    hits = fan_out(results, limit=HITS)
    searched = ", ".join(r.id for r in [repo, *named, *related])
    if not hits:
        if read_deep_meta(ws_root, repo.id) is None:
            notes.append(f"(A deep index adds code-graph symbols: `cairn deep build {repo.id}`.)")
        reason = results[repo.id].reason
        header = f"Nothing in {searched} matches that ({reason}). Start from these folders:"
        return clean_inline(header, 400), _layout(repo), notes
    top_repo = hits[0].repo or repo.id
    top = results[top_repo]
    header = f"{repo.id}: answered by {top.route} ({top.reason}"
    if "may be stale" in top.reason:
        header += f", rebuild with `cairn deep build {top_repo}`"
    header += ")"
    if named:
        header += f"; also searched {', '.join(r.id for r in named)}"
    if related:
        header += f"; also searched related repos: {', '.join(r.id for r in related)}"
    lines = [_line(hit, repo.id) for hit in hits]
    if any(result.truncated for result in results.values()):
        notes.append("(more files matched: ask a narrower question for the rest)")
    return clean_inline(header + ":", 500), lines, notes


def _locate(ws_root: Path, repos: list[Repo], question: str) -> dict[str, LocateResult]:
    if len(repos) <= 1:
        return {r.id: _one(ws_root, r, question) for r in repos}
    with ThreadPoolExecutor(max_workers=min(_WORKERS, len(repos))) as pool:
        done = pool.map(lambda r: _one(ws_root, r, question), repos)
        return {r.id: result for r, result in zip(repos, done, strict=True)}


def _one(ws_root: Path, repo: Repo, question: str) -> LocateResult:
    graph, stale = _graph(ws_root, repo)
    return hybrid_locate(ws_root / repo.path, question, graph, graph_stale=stale, limit=HITS)


def _graph(ws_root: Path, repo: Repo) -> tuple[Graph | None, bool]:
    meta = read_deep_meta(ws_root, repo.id)
    if meta is None:
        return None, False
    provider = providers.default_provider()
    graph = load_graph_cached(provider.graph_path(ws_root, repo.id))
    if graph is None:
        return None, False
    return graph, _deep_stale(provider, ws_root, repo, meta.built_at)


def _deep_stale(
    provider: GraphifyProvider, ws_root: Path, repo: Repo, built_at: str | None
) -> bool:
    root = ws_root / repo.path
    key = (str(root), head_sha(root), built_at)
    now = time.monotonic()
    with _STALE_LOCK:
        seen = _STALE.get(key)
        if seen is not None and now - seen[0] < STALE_TTL:
            return seen[1]
    stale = provider.status(ws_root, repo.id, root).stale
    with _STALE_LOCK:
        if len(_STALE) > 256:
            _STALE.clear()
        _STALE[key] = (now, stale)
    return stale


def _repos(workspace: Workspace, ids: list[str]) -> list[Repo]:
    return [r for r in (workspace.repo(i) for i in ids) if r is not None]


def _incomplete(ws_root: Path, repos: list[Repo]) -> list[str]:
    provider = providers.default_provider()
    return [
        f"({r.id}'s deep index is incomplete: rebuild it with `cairn deep build {r.id}`.)"
        for r in repos
        if read_deep_meta(ws_root, r.id) is not None
        and not provider.graph_path(ws_root, r.id).is_file()
    ]


def _line(hit: LocateHit, asked: str) -> str:
    path = hit.file if hit.repo in (None, asked) else f"{hit.repo}/{hit.file}"
    where = f"{path}:{hit.line}" if hit.line else path
    symbol = f" {hit.symbol} (graph)" if hit.symbol else ""
    return clean_inline(f"- {where}{symbol} — {hit.why}", 300)


def _layout(repo: Repo) -> list[str]:
    lines = [
        clean_inline(f"- {e.path}{f' → {e.purpose}' if e.purpose else ''}", 200)
        for e in repo.layout
    ]
    return lines or ["- (no layout recorded)"]
