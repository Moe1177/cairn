"""Render one repo card: a budgeted, agent-oriented summary of a repo."""

from dataclasses import dataclass

from cairn.model.graph import SYMMETRIC_TYPES, Edge, EdgeType, Repo, Workspace
from cairn.model.overrides import Authored
from cairn.render.tokens import estimate_tokens

SUMMARY_MAX = 500
_LIST_PREVIEW = 5


@dataclass(frozen=True)
class _Section:
    title: str
    items: tuple[str, ...]


def render_card(
    repo: Repo, workspace: Workspace, *, authored: Authored | None = None,
    note: str | None = None, budget: int = 800,
) -> str:
    text = _header(repo, authored)
    for section in _sections(repo, workspace, note):
        fitted = _fit(section, budget - estimate_tokens(text))
        if fitted:
            text += fitted
    return text


def _header(repo: Repo, authored: Authored | None) -> str:
    lines = [f"# {repo.id}", f"> {_summary(repo, authored)}", _meta(repo)]
    if any(root != repo.path for root in repo.app_roots):
        lines.append("app: " + ", ".join(f"`./{root}`" for root in repo.app_roots))
    return "\n".join(lines) + "\n"


def _summary(repo: Repo, authored: Authored | None) -> str:
    if authored and authored.summary:
        flat = " ".join(authored.summary.split())
        return flat if len(flat) <= SUMMARY_MAX else flat[: SUMMARY_MAX - 1] + "…"
    if repo.readme_excerpt:
        return f"{repo.readme_excerpt} (auto from README)"
    return "(no summary yet)"


def _meta(repo: Repo) -> str:
    parts = [f"`./{repo.path}`"]
    if repo.stack:
        parts.append(", ".join(repo.stack))
    if repo.head_sha:
        parts.append(f"HEAD {repo.head_sha}" + (" (uncommitted changes)" if repo.dirty else ""))
    return " · ".join(parts)


def _sections(repo: Repo, workspace: Workspace, note: str | None) -> list[_Section]:
    candidates = (
        _Section("Warnings", tuple(f"⚠ {e.detector} detector failed: {e.message}" for e in repo.detector_errors)),
        _Section("Relates", _relates(repo, workspace)),
        _Section("Run", tuple(f"{c.name} `{c.run}`" for c in repo.commands)),
        _Section("Layout", tuple(f"{e.path} → {e.purpose}" if e.purpose else e.path for e in repo.layout)),
        _Section("Exposes", tuple(f"{f.kind.value.replace('_', ' ')} {f.value}" for f in repo.contracts.exposes)),
        _Section("Notes", (note,) if note else ()),
    )
    return [s for s in candidates if s.items]


def _fit(section: _Section, remaining: int) -> str | None:
    items = list(section.items)
    for keep in range(len(items), 0, -1):
        lines = items[:keep]
        if keep < len(items):
            lines.append(f"…(+{len(items) - keep} more)")
        block = f"\n## {section.title}\n" + "\n".join(lines) + "\n"
        if estimate_tokens(block) <= remaining:
            return block
    return None


def _relates(repo: Repo, workspace: Workspace) -> tuple[str, ...]:
    edges = sorted(
        workspace.edges_for(repo.id),
        key=lambda e: (-e.confidence.rank, -e.score, e.source, e.target, e.type.value),
    )
    return tuple(_relate_line(repo.id, e) for e in edges)


def _relate_line(repo_id: str, edge: Edge) -> str:
    outgoing = edge.source == repo_id
    other = edge.target if outgoing else edge.source
    arrow = "→" if outgoing or edge.type in SYMMETRIC_TYPES else "←"
    why = f' — "{edge.why}"' if edge.why else ""
    return f"{arrow} {other}: {_describe(edge)}{why} ({_provenance(repo_id, edge)})"


def _signal_values(edge: Edge, prefix: str) -> list[str]:
    return [s.split(":", 1)[1] for s in edge.signals if s.startswith(prefix)]


def _join(values: list[str]) -> str:
    shown = ", ".join(values[:_LIST_PREVIEW])
    return shown + (f" +{len(values) - _LIST_PREVIEW} more" if len(values) > _LIST_PREVIEW else "")


def _describe(edge: Edge) -> str:
    if edge.type is EdgeType.SHARES_DB:
        parts = []
        tables = _signal_values(edge, "db_table:")
        if tables:
            parts.append("shares tables " + _join(tables))
        if _signal_values(edge, "db_project_ref:"):
            parts.append("same database project")
        return "; ".join(parts) or "shares a database"
    if edge.type is EdgeType.DEPENDS_ON_PACKAGE:
        return "uses package " + _join(_signal_values(edge, "package:"))
    if edge.type is EdgeType.PATH_REF:
        return "references path " + _join(_signal_values(edge, "path_ref:"))
    if edge.type is EdgeType.MENTIONS:
        return "docs mention"
    if edge.type is EdgeType.MANUAL:
        return edge.note or "linked manually"
    return edge.type.value.replace("_", " ")


def _provenance(repo_id: str, edge: Edge) -> str:
    if "manual" in edge.signals:
        return "manual"
    if not edge.evidence:
        return edge.confidence.value
    ev = edge.evidence[0]
    location = f"{ev.file}:{ev.line}" if ev.repo == repo_id else f"{ev.repo}/{ev.file}:{ev.line}"
    return f"{edge.confidence.value} · {location}"
