"""cairn MCP tool logic: workspace path + arguments in, short capped markdown out."""

from pathlib import Path

from cairn.discover.git import git_info
from cairn.emit import write_outputs
from cairn.integrations.claude import sync_claude
from cairn.load import load_authored
from cairn.model.graph import Confidence, Repo, Workspace
from cairn.paths import cards_dir
from cairn.render.card import relate_line
from cairn.resolve import resolve_repo
from cairn.scan import ScanResult, scan_workspace
from cairn.store.workspace_store import load_workspace

MAX_LINES = 30


def rescan(ws_root: Path) -> ScanResult:
    result = scan_workspace(ws_root)
    write_outputs(ws_root, result)
    sync_claude(ws_root)
    return result


def _workspace(ws_root: Path) -> Workspace:
    return load_workspace(ws_root) or rescan(ws_root).workspace


def _fresh(ws_root: Path, repo: Repo) -> Workspace:
    """Spec §17: re-scan when the repo's HEAD moved since the map was written."""
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
    matches = resolve_repo(workspace, load_authored(ws_root), name, limit=3)
    if matches and matches[0].score == 1.0:
        return workspace, workspace.repo(matches[0].repo_id), ""
    hint = ", ".join(m.repo_id for m in matches) or "none"
    return workspace, None, f"No repo named '{name}'. Did you mean: {hint}? (use resolve_repo)"


def resolve_text(ws_root: Path, query: str) -> str:
    workspace = _workspace(ws_root)
    matches = resolve_repo(workspace, load_authored(ws_root), query, limit=5)
    if not matches:
        known = ", ".join(r.id for r in workspace.repos[:MAX_LINES])
        return f"No repo matches '{query}'. Repos: {known}"
    return "\n".join(
        f"- {m.repo_id} ({m.score:.2f}): {m.one_liner} · `{m.path}` → .cairn/cards/{m.repo_id}.md"
        for m in matches
    )


def card_text(ws_root: Path, repo: str) -> str:
    _, found, message = _find(ws_root, repo)
    if found is None:
        return message
    _fresh(ws_root, found)
    path = cards_dir(ws_root) / f"{found.id}.md"
    if not path.is_file():
        return f"No card for {found.id} yet; call refresh."
    return path.read_text(encoding="utf-8")


def related_text(
    ws_root: Path, repo: str, edge_type: str | None = None, include_unconfirmed: bool = False
) -> str:
    workspace, found, message = _find(ws_root, repo)
    if found is None:
        return message
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


def find_across_text(ws_root: Path, query: str, kind: str | None = None) -> str:
    workspace = _workspace(ws_root)
    needle = query.strip().lower()
    lines: list[str] = []
    for repo in workspace.repos:
        sides = (("exposes", repo.contracts.exposes), ("consumes", repo.contracts.consumes))
        for direction, facts in sides:
            for fact in facts:
                if needle not in fact.value.lower() or (kind and fact.kind.value != kind):
                    continue
                ev = fact.evidence[0] if fact.evidence else None
                where = f" ({ev.file}:{ev.line})" if ev else ""
                label = fact.kind.value.replace("_", " ")
                lines.append(f"- {repo.id} {direction} {label} `{fact.value}`{where}")
    return "\n".join(_cap(lines)) if lines else f"Nothing in the map matches '{query}'."


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


def query_text(ws_root: Path, repo: str, question: str) -> str:
    _, found, message = _find(ws_root, repo)
    if found is None:
        return message
    layout = (
        "\n".join(f"- {e.path}{f' → {e.purpose}' if e.purpose else ''}" for e in found.layout)
        or "- (no layout recorded)"
    )
    return (
        f"No deep index is installed for {found.id} yet (graphify support arrives in a later "
        f"cairn release). To answer '{question}', start from these folders:\n{layout}"
    )
