"""cairn MCP tool logic: workspace path + arguments in, short capped markdown out."""

import functools
import threading
from collections.abc import Callable
from pathlib import Path

from cairn import providers
from cairn.discover.git import git_info
from cairn.emit import write_outputs
from cairn.errors import CairnError
from cairn.integrations.claude import sync_claude
from cairn.load import load_authored
from cairn.model.graph import Confidence, FactKind, Package, Repo, Workspace
from cairn.paths import cards_dir
from cairn.providers.graph import Hit, load_graph, rank
from cairn.providers.meta import read_deep_meta
from cairn.render.card import relate_line
from cairn.resolve import resolve_repo
from cairn.scan import ScanResult, scan_workspace
from cairn.security.text import clean_inline
from cairn.store.lock import workspace_lock
from cairn.store.workspace_store import load_workspace

MAX_LINES = 30
DEEP_HITS = 10


def rescan(ws_root: Path) -> ScanResult:
    with workspace_lock(ws_root):
        result = scan_workspace(ws_root)
        write_outputs(ws_root, result)
        sync_claude(ws_root)
        return result


LOCK_WAIT = 5.0
_NO_RESCAN = threading.local()


def locked(func: Callable[..., str]) -> Callable[..., str]:
    """Run a tool under the workspace lock so reads never race a concurrent rescan."""

    @functools.wraps(func)
    def wrapper(ws_root: Path, *args: object, **kwargs: object) -> str:
        try:
            with workspace_lock(ws_root, timeout=LOCK_WAIT):
                return func(ws_root, *args, **kwargs)
        except CairnError as exc:
            if "still updating" not in str(exc):
                raise
        # Another scan holds the lock: answer from the map on disk (atomically written, so
        # never half-updated) rather than leaving the agent waiting up to a minute.
        _NO_RESCAN.active = True
        try:
            text = func(ws_root, *args, **kwargs)
        finally:
            _NO_RESCAN.active = False
        return (
            f"{text}\n(note: another cairn process is updating this workspace; "
            "this answer may be slightly stale)"
        )

    return wrapper


def _workspace(ws_root: Path) -> Workspace:
    return load_workspace(ws_root) or rescan(ws_root).workspace


def _fresh(ws_root: Path, repo: Repo) -> Workspace:
    """Spec §17: re-scan when the repo's HEAD moved since the map was written."""
    if getattr(_NO_RESCAN, "active", False):
        return _workspace(ws_root)
    current = git_info(ws_root / repo.path).head_sha
    if current and repo.head_sha and current != repo.head_sha:
        return rescan(ws_root).workspace
    return _workspace(ws_root)


def _cap(lines: list[str]) -> list[str]:
    if len(lines) <= MAX_LINES:
        return lines
    return [*lines[:MAX_LINES], f"…(+{len(lines) - MAX_LINES} more)"]


def _find(ws_root: Path, name: str) -> tuple[Workspace, Repo | None, str]:
    workspace = _workspace(ws_root)
    lowered = name.strip().lower()
    for repo in workspace.repos:
        if lowered == repo.id.lower() or lowered in (a.lower() for a in repo.aliases):
            return workspace, repo, ""
    owner = _package_owner(workspace, lowered)
    if owner is not None:
        return workspace, owner[0], ""
    matches = resolve_repo(workspace, load_authored(ws_root), name, limit=3)
    if matches and matches[0].score == 1.0:
        return workspace, workspace.repo(matches[0].repo_id), ""
    hint = ", ".join(m.repo_id for m in matches) or "none"
    return workspace, None, f"No repo named '{name}'. Did you mean: {hint}? (use resolve_repo)"


def _package_owners(workspace: Workspace, lowered: str) -> list[tuple[Repo, Package]]:
    """Every repo whose monorepo contains a package with this exact name (spec §21.4)."""
    return [
        (repo, package)
        for repo in workspace.repos
        for package in repo.packages
        if package.name.lower() == lowered
    ]


def _package_owner(workspace: Workspace, lowered: str) -> tuple[Repo, Package] | None:
    owners = _package_owners(workspace, lowered)
    return owners[0] if owners else None


def _names_a_repo(workspace: Workspace, lowered: str) -> bool:
    return any(
        lowered == r.id.lower() or lowered in (a.lower() for a in r.aliases)
        for r in workspace.repos
    )


@locked
def resolve_text(ws_root: Path, query: str) -> str:
    workspace = _workspace(ws_root)
    lowered = query.strip().lower()
    # A repo's own name always wins; then every repo holding a package by that name.
    owners = [] if _names_a_repo(workspace, lowered) else _package_owners(workspace, lowered)
    if owners:
        return "\n".join(
            clean_inline(
                f"- {repo.id}: package {package.name} at `{package.path}` "
                f"→ .cairn/cards/{repo.id}.md",
                400,
            )
            for repo, package in owners[:MAX_LINES]
        )
    matches = resolve_repo(workspace, load_authored(ws_root), query, limit=5)
    if not matches:
        known = ", ".join(r.id for r in workspace.repos[:MAX_LINES])
        return f"No repo matches '{query}'. Repos: {known}"
    return "\n".join(
        f"- {m.repo_id} ({m.score:.2f}): {m.one_liner} · `{m.path}` → .cairn/cards/{m.repo_id}.md"
        for m in matches
    )


@locked
def card_text(ws_root: Path, repo: str) -> str:
    _, found, message = _find(ws_root, repo)
    if found is None:
        return message
    _fresh(ws_root, found)
    path = cards_dir(ws_root) / f"{found.id}.md"
    if not path.is_file():
        return f"No card for {found.id} yet; call refresh."
    return path.read_text(encoding="utf-8")


@locked
def related_text(
    ws_root: Path, repo: str, edge_type: str | None = None, include_unconfirmed: bool = False
) -> str:
    _, found, message = _find(ws_root, repo)
    if found is None:
        return message
    workspace = _fresh(ws_root, found)
    edges = [
        e
        for e in workspace.edges_for(found.id)
        if (edge_type is None or e.type.value == edge_type)
        and (include_unconfirmed or e.confidence is not Confidence.AMBIGUOUS)
    ]
    if not edges:
        return f"No matching relationships for {found.id}."
    edges.sort(key=lambda e: (-e.confidence.rank, -e.score, e.key))
    lines = _cap([relate_line(found.id, e) for e in edges])
    return "\n".join([f"{found.id} relationships ({len(edges)}):", *lines])


@locked
def find_across_text(ws_root: Path, query: str, kind: str | None = None) -> str:
    workspace = _workspace(ws_root)
    needle = query.strip().lower()
    lines: list[str] = []
    for repo in workspace.repos:
        sides = (("exposes", repo.contracts.exposes), ("consumes", repo.contracts.consumes))
        for direction, facts in sides:
            for fact in facts:
                if fact.kind is FactKind.COMPOSE_SERVICE:
                    continue  # internal service-to-repo wiring; the edges show the result
                if needle not in fact.value.lower() or (kind and fact.kind.value != kind):
                    continue
                ev = fact.evidence[0] if fact.evidence else None
                where = f" ({ev.file}:{ev.line})" if ev else ""
                label = fact.kind.value.replace("_", " ")
                line = f"- {repo.id} {direction} {label} '{fact.value}'{where}"
                lines.append(clean_inline(line, 400))
    return "\n".join(_cap(lines)) if lines else f"Nothing in the map matches '{query}'."


@locked
def refresh_text(ws_root: Path) -> str:
    previous = load_workspace(ws_root)
    before = {r.id: r.head_sha for r in previous.repos} if previous else {}
    workspace = rescan(ws_root).workspace
    changed = [r.id for r in workspace.repos if before.get(r.id) != r.head_sha]
    detail = f": {', '.join(changed[:10])}" if changed else ""
    return (
        f"Refreshed {len(workspace.repos)} repos ({len(changed)} changed{detail}); "
        f"{len(workspace.edges)} relationships."
    )


@locked
def query_text(ws_root: Path, repo: str, question: str) -> str:
    _, found, message = _find(ws_root, repo)
    if found is None:
        return message
    found = _fresh(ws_root, found).repo(found.id) or found
    deep = _deep_answer(ws_root, found, question)
    if deep is not None:
        return deep
    return (
        f"No deep index for {found.id} yet. Build one with `cairn deep build {found.id}` "
        "(needs graphify: pip install 'cairnmap[graphify]'). "
        f"Meanwhile, start from these folders:\n{_layout(found)}"
    )


def _layout(repo: Repo) -> str:
    return (
        "\n".join(
            clean_inline(f"- {e.path}{f' → {e.purpose}' if e.purpose else ''}", 200)
            for e in repo.layout
        )
        or "- (no layout recorded)"
    )


def _deep_answer(ws_root: Path, repo: Repo, question: str) -> str | None:
    """Spec §23: answer from the repo's code graph, offline, without running graphify."""
    meta = read_deep_meta(ws_root, repo.id)
    if meta is None:
        return None
    provider = providers.default_provider()
    graph = load_graph(provider.graph_path(ws_root, repo.id))
    if graph is None:
        return None
    header = f"{repo.id} deep index ({meta.provider}, {meta.nodes} symbols)"
    if provider.status(ws_root, repo.id, ws_root / repo.path).stale:
        header += f"; may be stale, rebuild with `cairn deep build {repo.id}`"
    hits = rank(graph, question, DEEP_HITS)
    if not hits:
        busiest = ", ".join(meta.hubs) or "none recorded"
        line = clean_inline(f"{header}: no symbol matches. Busiest symbols: {busiest}", 400)
        return f"{line}\nFolders:\n{_layout(repo)}"
    return "\n".join([clean_inline(f"{header}:", 200), *_cap([_hit_line(h) for h in hits])])


def _hit_line(hit: Hit) -> str:
    where = ""
    if hit.file:
        where = f" — {hit.file}" + (f":{hit.line}" if hit.line else "")
    near = f" (near: {', '.join(hit.neighbours)})" if hit.neighbours else ""
    return clean_inline(f"- {hit.label}{where}{near}", 400)
