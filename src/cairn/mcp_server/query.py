"""The MCP `query` tool: where in the code a question is answered.

Grep first, the code graph as a backstop (see cairn.locate.hybrid for the measurements behind
that order). Searches the repo asked about and any other repo the question names; when those
have nothing, the repos the map relates to it. Says which locator answered and why.
"""

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cairn import providers
from cairn.discover.git import head_sha
from cairn.locate.hybrid import hybrid_locate
from cairn.locate.model import LocateHit, LocateResult
from cairn.locate.workspace import fan_out
from cairn.model.graph import Confidence, Repo, Workspace
from cairn.providers.graph import Graph, load_graph_cached
from cairn.providers.graphify import GraphifyProvider
from cairn.providers.meta import read_deep_meta
from cairn.security.text import clean_inline

HITS = 10
NAMED_MAX = 4
RELATED_MAX = 5
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
    named = _named(workspace, repo, question)
    results = _locate(ws_root, [repo, *named], question)
    related: list[Repo] = []
    if not any(result.hits for result in results.values()):
        related = _related(workspace, repo, exclude={repo.id, *(r.id for r in named)})
        results.update(_locate(ws_root, related, question))
    notes = _incomplete(ws_root, [repo, *named, *related])
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
    if related:
        header += f"; nothing in {repo.id}, so searched related repos: "
        header += ", ".join(r.id for r in related)
    elif named:
        header += f"; also searched {', '.join(r.id for r in named)}"
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


def _named(workspace: Workspace, repo: Repo, question: str) -> list[Repo]:
    """Other repos the question names by id or alias, as whole words."""
    text = question[:4000].lower()
    found = []
    for other in workspace.repos:
        if other.id == repo.id:
            continue
        names = (other.id.lower(), *(a.lower() for a in other.aliases))
        if any(re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", text) for n in names if n):
            found.append(other)
    return found[:NAMED_MAX]


def _related(workspace: Workspace, repo: Repo, exclude: set[str]) -> list[Repo]:
    edges = sorted(
        (e for e in workspace.edges_for(repo.id) if e.confidence is not Confidence.AMBIGUOUS),
        key=lambda e: (-e.confidence.rank, -e.score, e.key),
    )
    found: list[Repo] = []
    for edge in edges:
        other = workspace.repo(edge.target if edge.source == repo.id else edge.source)
        if other is not None and other.id not in exclude and other not in found:
            found.append(other)
    return found[:RELATED_MAX]


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
    symbol = f" {hit.symbol}" if hit.symbol else ""
    return clean_inline(f"- {where}{symbol} — {hit.why}", 300)


def _layout(repo: Repo) -> list[str]:
    lines = [
        clean_inline(f"- {e.path}{f' → {e.purpose}' if e.purpose else ''}", 200)
        for e in repo.layout
    ]
    return lines or ["- (no layout recorded)"]
