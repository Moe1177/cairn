"""Apply relations.yaml and authored reviews on top of detected edges."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from cairn.match.matcher import merge_edges
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
        if not _removed(e, relations.remove_edges) and reviews.get(e.key) != "rejected"
    ]
    manual, warnings = _manual_edges(relations, known_ids, whys)
    warnings += _unknown_keys("aliases", relations.aliases, known_ids)
    warnings += _unknown_keys("notes", relations.notes, known_ids)
    return OverrideResult(edges=merge_edges([*kept, *manual]), warnings=tuple(warnings))


def _annotate(edge: Edge, reviews: Mapping[str, str], whys: Mapping[str, str]) -> Edge:
    update: dict[str, object] = {}
    if reviews.get(edge.key) == "confirmed" and edge.confidence is Confidence.AMBIGUOUS:
        update["confidence"] = Confidence.INFERRED
    if edge.key in whys:
        update["why"] = whys[edge.key]
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
            Edge(source=rule.source, target=rule.target, type=rule.type, confidence=Confidence.EXTRACTED,
                 score=1.0, signals=("manual",), note=rule.note, why=whys.get(key))
        )
    return edges, warnings


def _unknown_keys(section: str, mapping: Mapping[str, object], known_ids: frozenset[str]) -> list[str]:
    return [
        f"relations.yaml: {section} references unknown repo '{repo_id}'"
        for repo_id in sorted(mapping)
        if repo_id not in known_ids
    ]
