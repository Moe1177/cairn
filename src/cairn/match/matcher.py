"""Pair one repo's consumes with another repo's exposes to build edges."""

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import combinations

from cairn.match.scoring import DEFAULT_TABLE_STOPLIST, db_confidence, noisy_or, specificity
from cairn.model.graph import (
    MAX_EVIDENCE,
    SYMMETRIC_TYPES,
    Confidence,
    Contracts,
    Edge,
    EdgeType,
    Evidence,
    Fact,
    FactKind,
)


@dataclass(frozen=True)
class RepoFacts:
    id: str
    path: str
    contracts: Contracts


@dataclass(frozen=True)
class _TableRefs:
    refs: dict[str, tuple[Evidence, ...]]
    created: frozenset[str]


def match_edges(
    repos: Sequence[RepoFacts], *, stop_tables: frozenset[str] = DEFAULT_TABLE_STOPLIST
) -> tuple[Edge, ...]:
    ordered = sorted(repos, key=lambda r: r.id)
    return merge_edges(
        [
            *_package_edges(ordered),
            *_db_edges(ordered, stop_tables),
            *_project_ref_edges(ordered),
            *_path_edges(ordered),
            *_mention_edges(ordered),
        ]
    )


def merge_edges(edges: Iterable[Edge]) -> tuple[Edge, ...]:
    merged: dict[tuple[str, str, str], Edge] = {}
    for edge in edges:
        key = _merge_key(edge)
        current = merged.get(key)
        merged[key] = edge if current is None else _combine(current, edge)
    return tuple(sorted(merged.values(), key=lambda e: (e.source, e.target, e.type.value)))


def _facts(repo: RepoFacts, exposes: bool, kind: FactKind) -> list[Fact]:
    pool = repo.contracts.exposes if exposes else repo.contracts.consumes
    return [f for f in pool if f.kind is kind]


def _edge(
    source: str,
    target: str,
    type_: EdgeType,
    confidence: Confidence,
    score: float,
    signals: Iterable[str],
    evidence: Iterable[Evidence],
) -> Edge:
    return Edge(
        source=source,
        target=target,
        type=type_,
        confidence=confidence,
        score=score,
        signals=tuple(dict.fromkeys(signals)),
        evidence=tuple(dict.fromkeys(evidence))[:MAX_EVIDENCE],
    )


def _package_edges(repos: list[RepoFacts]) -> list[Edge]:
    owners: dict[str, str] = {}
    for repo in repos:
        for fact in _facts(repo, True, FactKind.PACKAGE):
            owners.setdefault(fact.value, repo.id)
    return [
        _edge(
            repo.id,
            owners[f.value],
            EdgeType.DEPENDS_ON_PACKAGE,
            Confidence.EXTRACTED,
            1.0,
            [f"package:{f.value}"],
            f.evidence,
        )
        for repo in repos
        for f in _facts(repo, False, FactKind.PACKAGE)
        if owners.get(f.value) not in (None, repo.id)
    ]


def _table_refs(repo: RepoFacts, stop: frozenset[str]) -> _TableRefs:
    refs: dict[str, tuple[Evidence, ...]] = {}
    created = {f.value for f in _facts(repo, True, FactKind.DB_TABLE)}
    for fact in (*_facts(repo, True, FactKind.DB_TABLE), *_facts(repo, False, FactKind.DB_TABLE)):
        if fact.value not in stop:
            refs[fact.value] = refs.get(fact.value, ()) + fact.evidence
    return _TableRefs(refs=refs, created=frozenset(created))


def _db_edges(repos: list[RepoFacts], stop: frozenset[str]) -> list[Edge]:
    tables = {r.id: _table_refs(r, stop) for r in repos}
    df = Counter(name for refs in tables.values() for name in refs.refs)
    edges = []
    for a, b in combinations([r.id for r in repos], 2):
        shared = sorted(set(tables[a].refs) & set(tables[b].refs))
        score = noisy_or(specificity(df[t]) for t in shared) if shared else 0.0
        confidence = db_confidence(score)
        if confidence is None:
            continue
        if (
            confidence is Confidence.EXTRACTED
            and _owned_by_one_side(shared, tables[a], tables[b]) < 2
        ):
            # Same names alone (e.g. both apps create `profiles`) don't prove a shared database.
            confidence = Confidence.INFERRED
        source, target = _db_direction(a, b, shared, tables)
        evidence = [
            ev for t in shared for ev in (*tables[source].refs[t][:1], *tables[target].refs[t][:1])
        ]
        edges.append(
            _edge(
                source,
                target,
                EdgeType.SHARES_DB,
                confidence,
                score,
                [f"db_table:{t}" for t in shared],
                evidence,
            )
        )
    return edges


def _owned_by_one_side(shared: list[str], a: _TableRefs, b: _TableRefs) -> int:
    """Shared tables that exactly one repo creates and the other only queries."""
    return sum((t in a.created) != (t in b.created) for t in shared)


def _db_direction(
    a: str, b: str, shared: list[str], tables: dict[str, _TableRefs]
) -> tuple[str, str]:
    a_created = len(set(shared) & tables[a].created)
    b_created = len(set(shared) & tables[b].created)
    return (b, a) if a_created > b_created else (a, b)


def _project_ref_edges(repos: list[RepoFacts]) -> list[Edge]:
    by_ref: dict[str, list[tuple[str, Fact]]] = {}
    for repo in repos:
        for fact in _facts(repo, False, FactKind.DB_PROJECT_REF):
            by_ref.setdefault(fact.value, []).append((repo.id, fact))
    return [
        _edge(
            a_id,
            b_id,
            EdgeType.SHARES_DB,
            Confidence.EXTRACTED,
            1.0,
            [f"db_project_ref:{ref}"],
            (*a_fact.evidence, *b_fact.evidence),
        )
        for ref, members in by_ref.items()
        for (a_id, a_fact), (b_id, b_fact) in combinations(members, 2)
    ]


def _path_edges(repos: list[RepoFacts]) -> list[Edge]:
    by_length = sorted(repos, key=lambda r: len(r.path), reverse=True)
    edges = []
    for repo in repos:
        for fact in _facts(repo, False, FactKind.PATH_REF):
            target = next(
                (
                    r
                    for r in by_length
                    if fact.value == r.path or fact.value.startswith(f"{r.path}/")
                ),
                None,
            )
            if target is not None and target.id != repo.id:
                edges.append(
                    _edge(
                        repo.id,
                        target.id,
                        EdgeType.PATH_REF,
                        Confidence.EXTRACTED,
                        1.0,
                        [f"path_ref:{fact.value}"],
                        fact.evidence,
                    )
                )
    return edges


def _mention_edges(repos: list[RepoFacts]) -> list[Edge]:
    known = {r.id for r in repos}
    return [
        _edge(
            repo.id,
            f.value,
            EdgeType.MENTIONS,
            Confidence.INFERRED,
            0.5,
            ["doc_mention"],
            f.evidence,
        )
        for repo in repos
        for f in _facts(repo, False, FactKind.DOC_MENTION)
        if f.value in known and f.value != repo.id
    ]


def _merge_key(edge: Edge) -> tuple[str, str, str]:
    if edge.type in SYMMETRIC_TYPES:
        a, b = sorted((edge.source, edge.target))
        return a, b, edge.type.value
    return edge.source, edge.target, edge.type.value


def _combine(a: Edge, b: Edge) -> Edge:
    return a.model_copy(
        update={
            "confidence": a.confidence if a.confidence.rank >= b.confidence.rank else b.confidence,
            "score": max(a.score, b.score),
            "signals": tuple(dict.fromkeys((*a.signals, *b.signals))),
            "evidence": tuple(dict.fromkeys((*a.evidence, *b.evidence)))[:MAX_EVIDENCE],
            "why": a.why or b.why,
            "note": a.note or b.note,
        }
    )
