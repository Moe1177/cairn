"""Which repos a repo is linked to, one line each (spec §28): the answer to "what does this repo
link to?", the same in the terminal (`cairn links`) and in every agent (the `links` MCP tool).

    trips-svc is linked to 2 repos:
      admin-console  ↔ both ways  shares 2 tables, mentions each other in docs
      rider-web      ← one way    calls this repo (3 routes)

Direction is from the asked-about repo: → one way (it uses the other repo), ← one way (the other
repo uses it), ↔ both ways (each uses the other, or they share something, like a database).
Phrases name the other repo "it" and the asked-about repo "this repo".
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cairn.detectors.aws_names import EVENT_SOURCE, KIND_LABELS
from cairn.model.graph import SYMMETRIC_TYPES, Confidence, Edge, EdgeType, Repo, Workspace
from cairn.render.card import relate_line
from cairn.security.text import clean_inline

ONE_WAY_OUT = "→ one way"
ONE_WAY_IN = "← one way"
BOTH_WAYS = "↔ both ways"
_LIST_PREVIEW = 3
_LINE_MAX = 400


@dataclass(frozen=True)
class Neighbor:
    repo: str
    direction: str  # one of ONE_WAY_OUT, ONE_WAY_IN, BOTH_WAYS
    phrases: tuple[str, ...]
    edges: tuple[Edge, ...]


def neighbors(
    workspace: Workspace, repo_id: str, *, include_unconfirmed: bool = False
) -> tuple[Neighbor, ...]:
    """The repos linked to `repo_id`, alphabetically. Unconfirmed links only on request."""
    grouped: dict[str, list[Edge]] = {}
    for edge in workspace.edges_for(repo_id):
        if edge.confidence is Confidence.AMBIGUOUS and not include_unconfirmed:
            continue
        other = edge.target if edge.source == repo_id else edge.source
        if other != repo_id:
            grouped.setdefault(other, []).append(edge)
    return tuple(_neighbor(repo_id, other, edges) for other, edges in sorted(grouped.items()))


def hidden_count(workspace: Workspace, repo_id: str) -> int:
    """Repos linked only by unconfirmed links (shown with --all / include_unconfirmed)."""
    shown = {n.repo for n in neighbors(workspace, repo_id)}
    every = {n.repo for n in neighbors(workspace, repo_id, include_unconfirmed=True)}
    return len(every - shown)


def render_links(
    repo_id: str,
    found: tuple[Neighbor, ...],
    *,
    evidence: bool = False,
    hidden: int = 0,
    show_all: str = "--all",
) -> str:
    name = clean_inline(repo_id, 80)
    if not found:
        lines = [f"{name} is not linked to any other repo in this map."]
    else:
        noun = "repo" if len(found) == 1 else "repos"
        lines = [f"{name} is linked to {len(found)} {noun}:"]
        names = [clean_inline(n.repo, 80) for n in found]
        width = max(len(n) for n in names)
        for neighbor, other in zip(found, names, strict=True):
            # Repo names and phrases come from repo files: each is cleaned to one safe line.
            summary = clean_inline(", ".join(neighbor.phrases), _LINE_MAX)
            lines.append(
                f"  {other.ljust(width)}  {neighbor.direction.ljust(len(BOTH_WAYS))}  {summary}"
            )
            if evidence:
                lines += [f"      {relate_line(repo_id, e)}" for e in neighbor.edges]
    if hidden:
        noun = "repo is" if hidden == 1 else "repos are"
        lines.append(
            f"({hidden} more {noun} linked only by unconfirmed links; include them with {show_all}.)"
        )
    return "\n".join(lines)


def links_json(repo_id: str, found: tuple[Neighbor, ...]) -> dict:
    return {
        "repo": repo_id,
        "links": [
            {
                "repo": n.repo,
                "direction": {ONE_WAY_OUT: "out", ONE_WAY_IN: "in"}.get(n.direction, "both"),
                "summary": list(n.phrases),
                "edges": [
                    {
                        "type": e.type.value,
                        "from": e.source,
                        "to": e.target,
                        "confidence": e.confidence.value,
                        "evidence": [f"{ev.repo}/{ev.file}:{ev.line}" for ev in e.evidence],
                    }
                    for e in n.edges
                ],
            }
            for n in found
        ],
    }


def repo_at(workspace: Workspace, ws_root: Path, folder: Path) -> Repo | None:
    """The repo that contains `folder` (the deepest, for nested repos), if any."""
    try:
        target = folder.resolve()
    except OSError:
        return None
    inside = []
    for repo in workspace.repos:
        root = (ws_root / repo.path).resolve()
        if target == root or root in target.parents:
            inside.append((len(root.parts), repo))
    return max(inside, key=lambda pair: pair[0])[1] if inside else None


def _neighbor(repo_id: str, other: str, edges: list[Edge]) -> Neighbor:
    ordered = sorted(edges, key=lambda e: (-e.confidence.rank, e.type.value, e.source))
    outgoing = any(e.source == repo_id and e.type not in SYMMETRIC_TYPES for e in ordered)
    incoming = any(e.target == repo_id and e.type not in SYMMETRIC_TYPES for e in ordered)
    mutual = any(e.type in SYMMETRIC_TYPES for e in ordered)
    if mutual or (outgoing and incoming):
        direction = BOTH_WAYS
    else:
        direction = ONE_WAY_OUT if outgoing else ONE_WAY_IN
    # Shared things first, then what this repo does to the other, then what the other does back.
    by_side = sorted(
        ordered,
        key=lambda e: 0 if e.type in SYMMETRIC_TYPES else 1 if e.source == repo_id else 2,
    )
    phrases = [_phrase(e, e.source == repo_id) for e in by_side]
    if "mentions it in docs" in phrases and "mentions this repo in docs" in phrases:
        phrases = [p for p in phrases if p != "mentions this repo in docs"]
        phrases[phrases.index("mentions it in docs")] = "mentions each other in docs"
    return Neighbor(
        repo=other, direction=direction, phrases=tuple(dict.fromkeys(phrases)), edges=tuple(ordered)
    )


def _phrase(edge: Edge, outgoing: bool) -> str:
    text = _PHRASES.get(edge.type, _generic)(edge, outgoing)
    return f"{text} (unconfirmed)" if edge.confidence is Confidence.AMBIGUOUS else text


def _values(edge: Edge, prefix: str) -> list[str]:
    return [s.split(":", 1)[1] for s in edge.signals if s.startswith(prefix)]


def _join(values: list[str]) -> str:
    shown = ", ".join(values[:_LIST_PREVIEW])
    more = len(values) - _LIST_PREVIEW
    return shown + (f" +{more} more" if more > 0 else "")


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def _side(outgoing: bool, out: str, back: str) -> str:
    return out if outgoing else back


def _calls(edge: Edge, outgoing: bool) -> str:
    routes = _values(edge, "http_route:")
    detail = f" ({_count(len(routes), 'route')})" if routes else ""
    return _side(outgoing, "calls it", "calls this repo") + detail


def _grpc(edge: Edge, outgoing: bool) -> str:
    services = _join(_values(edge, "grpc:"))
    return _side(outgoing, f"calls its gRPC {services}", f"calls this repo's gRPC {services}")


def _pubsub(edge: Edge, outgoing: bool) -> str:
    topics = _join([t.removeprefix(EVENT_SOURCE) for t in _values(edge, "topic:")])
    return _side(outgoing, f"sends it events ({topics})", f"sends this repo events ({topics})")


def _package(edge: Edge, outgoing: bool) -> str:
    packages = _join(_values(edge, "package:"))
    return _side(outgoing, f"uses its package {packages}", f"uses this repo's package {packages}")


def _resource(edge: Edge, outgoing: bool) -> str:
    def label(value: str) -> str:
        kind, _, name = value.partition(":")
        return f"{KIND_LABELS.get(kind, kind)} {name}"

    used = [label(v) for v in _values(edge, "resource:") + _values(edge, "ssm_named:")]
    used += [f"Render {v}" for v in _values(edge, "render:")]
    what = _join(used) or "a cloud resource"
    return _side(outgoing, f"uses its {what}", f"uses this repo's {what}")


def _generic(edge: Edge, outgoing: bool) -> str:
    if edge.type is EdgeType.MANUAL:
        return edge.note or "linked by hand"
    return edge.type.value.replace("_", " ")


_PHRASES: dict[EdgeType, Callable[[Edge, bool], str]] = {
    EdgeType.CALLS_HTTP: _calls,
    EdgeType.GRPC: _grpc,
    EdgeType.PUBSUB: _pubsub,
    EdgeType.DEPENDS_ON_PACKAGE: _package,
    EdgeType.USES_RESOURCE: _resource,
    EdgeType.PATH_REF: lambda e, out: _side(
        out, "references its files", "references this repo's files"
    ),
    EdgeType.COMPOSE_LINK: lambda e, out: _side(
        out, "depends on it in compose", "depends on this repo in compose"
    ),
    EdgeType.DEPLOYS: lambda e, out: _side(out, "deploys it", "deploys this repo"),
    EdgeType.MENTIONS: lambda e, out: _side(
        out, "mentions it in docs", "mentions this repo in docs"
    ),
    EdgeType.SHARES_DB: lambda e, out: (
        f"shares {_count(len(_values(e, 'db_table:')), 'table')}"
        if _values(e, "db_table:")
        else "shares a database"
    ),
    EdgeType.SHARES_ENV: lambda e, out: f"shares {_count(len(_values(e, 'env:')), 'env var')}",
    EdgeType.MIRRORS: lambda e, out: "copy of the same app",
}
