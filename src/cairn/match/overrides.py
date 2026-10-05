"""Apply relations.yaml and authored reviews on top of detected edges."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from cairn.match.matcher import corroborate, merge_edges
from cairn.model.graph import SYMMETRIC_TYPES, Confidence, Edge
from cairn.model.overrides import Authored, Relations, RemovedEdge


@dataclass(frozen=True)
class OverrideResult:
    edges: tuple[Edge, ...]
    warnings: tuple[str, ...]


def apply_overrides(
    edges: Iterable[Edge],
    relations: Relations,
    authored: Mapping[str, Authored],
    known_ids: frozenset[str],
) -> OverrideResult:
    reviews = {k: v for a in authored.values() for k, v in a.edge_reviews.items()}
    whys = {k: v for a in authored.values() for k, v in a.edge_whys.items()}
    kept = [
        _annotate(e, reviews, whys)
        for e in edges
        if not _removed(e, relations.remove_edges) and _lookup(reviews, e) != "rejected"
    ]
    manual, warnings = _manual_edges(relations, known_ids, whys)
    warnings += _unknown_keys("aliases", relations.aliases, known_ids)
    warnings += _unknown_keys("notes", relations.notes, known_ids)
    # Corroborate last, so rejected/removed edges can't vouch and manual links can (spec §16.2).
    edges = corroborate(merge_edges([*kept, *manual]))
    return OverrideResult(edges=edges, warnings=tuple(warnings))


def edge_keys(edge: Edge) -> tuple[str, ...]:
    """Keys an author may use for this edge; symmetric edges match either direction."""
    if edge.type in SYMMETRIC_TYPES:
        return (edge.key, f"{edge.target}->{edge.source}:{edge.type.value}")
    return (edge.key,)


def _lookup(mapping: Mapping[str, str], edge: Edge) -> str | None:
    return next((mapping[k] for k in edge_keys(edge) if k in mapping), None)


def _annotate(edge: Edge, reviews: Mapping[str, str], whys: Mapping[str, str]) -> Edge:
    update: dict[str, object] = {}
    if _lookup(reviews, edge) == "confirmed" and edge.confidence is Confidence.AMBIGUOUS:
        update["confidence"] = Confidence.INFERRED
    why = _lookup(whys, edge)
    if why is not None:
        update["why"] = why
    return edge.model_copy(update=update) if update else edge


def _removed(edge: Edge, removals: Iterable[RemovedEdge]) -> bool:
    for rule in removals:
        if rule.type is not None and rule.type is not edge.type:
            continue
        same = (rule.source, rule.target) == (edge.source, edge.target)
        flipped = (rule.target, rule.source) == (edge.source, edge.target)
        if same or (flipped and edge.type in SYMMETRIC_TYPES):
            return True
    return False


def _manual_edges(
    relations: Relations, known_ids: frozenset[str], whys: Mapping[str, str]
) -> tuple[list[Edge], list[str]]:
    edges: list[Edge] = []
    warnings: list[str] = []
    for rule in relations.edges:
        missing = [i for i in (rule.source, rule.target) if i not in known_ids]
        if missing:
            warnings.append(
                f"relations.yaml: edge {rule.source} -> {rule.target} references unknown repo(s): "
                f"{', '.join(missing)}"
            )
            continue
        key = f"{rule.source}->{rule.target}:{rule.type.value}"
        edges.append(
            Edge(
                source=rule.source,
                target=rule.target,
                type=rule.type,
                confidence=Confidence.EXTRACTED,
                score=1.0,
                signals=("manual",),
                note=rule.note,
                why=whys.get(key),
            )
        )
    return edges, warnings


def _unknown_keys(
    section: str, mapping: Mapping[str, object], known_ids: frozenset[str]
) -> list[str]:
    return [
        f"relations.yaml: {section} references unknown repo '{repo_id}'"
        for repo_id in sorted(mapping)
        if repo_id not in known_ids
    ]
