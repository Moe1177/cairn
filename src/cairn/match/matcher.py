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

# Spec §16.3: a local Supabase id (folder-name default) is not database identity.
_LOCAL_REF = "supabase-local:"


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
    merged = merge_edges(
        [
            *_package_edges(ordered),
            *_db_edges(ordered, stop_tables),
            *_project_ref_edges(ordered),
            *_path_edges(ordered),
            *_mention_edges(ordered),
        ]
    )
    return merged  # corroboration runs after overrides (see match.overrides)


def merge_edges(edges: Iterable[Edge]) -> tuple[Edge, ...]:
    merged: dict[tuple[str, str, str], Edge] = {}
    for edge in edges:
        key = _merge_key(edge)
        current = merged.get(key)
        merged[key] = edge if current is None else _combine(current, edge)
    return tuple(sorted(merged.values(), key=lambda e: (e.source, e.target, e.type.value)))


def corroborate(edges: Iterable[Edge]) -> tuple[Edge, ...]:
    """Spec §16.2: upgrade shares_db one tier when another edge type links the same pair."""
    items = list(edges)
    by_pair: dict[frozenset[str], list[Edge]] = {}
    for edge in items:
        by_pair.setdefault(frozenset((edge.source, edge.target)), []).append(edge)
    return tuple(_corroborated(e, by_pair[frozenset((e.source, e.target))]) for e in items)


def _corroborated(edge: Edge, same_pair: list[Edge]) -> Edge:
    if edge.type is not EdgeType.SHARES_DB:
        return edge
    # Only independent, non-ambiguous evidence corroborates (spec §16.2, review fix).
    others = [
        o
        for o in same_pair
        if o.type is not EdgeType.SHARES_DB and o.confidence.rank >= Confidence.INFERRED.rank
    ]
    strong = [o for o in others if o.confidence is Confidence.EXTRACTED]
    if edge.confidence is Confidence.AMBIGUOUS and others:
        upgraded, by = Confidence.INFERRED, others[0]
    elif edge.confidence is Confidence.INFERRED and strong:
        upgraded, by = Confidence.EXTRACTED, strong[0]
    else:
        return edge
    signals = (*edge.signals, f"corroborated:{by.type.value}")
    return edge.model_copy(update={"confidence": upgraded, "signals": signals})


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
    owners: dict[str, list[str]] = {}
    for repo in repos:
        for fact in _facts(repo, True, FactKind.PACKAGE):
            owners.setdefault(fact.value, []).append(repo.id)
    edges = []
    for repo in repos:
        for fact in _facts(repo, False, FactKind.PACKAGE):
            candidates = [o for o in owners.get(fact.value, []) if o != repo.id]
            # Two repos publishing the same name: we can't tell which one is consumed.
            unique = len(candidates) == 1
            edges += [
                _edge(
                    repo.id,
                    owner,
                    EdgeType.DEPENDS_ON_PACKAGE,
                    Confidence.EXTRACTED if unique else Confidence.AMBIGUOUS,
                    1.0 if unique else 0.3,
                    [f"package:{fact.value}"],
                    fact.evidence,
                )
                for owner in candidates
            ]
    return edges


def _table_refs(repo: RepoFacts, stop: frozenset[str]) -> _TableRefs:
    refs: dict[str, tuple[Evidence, ...]] = {}
    created = {f.value for f in _facts(repo, True, FactKind.DB_TABLE)}
    for fact in (*_facts(repo, True, FactKind.DB_TABLE), *_facts(repo, False, FactKind.DB_TABLE)):
        if fact.value not in stop:
            refs[fact.value] = refs.get(fact.value, ()) + fact.evidence
    return _TableRefs(refs=refs, created=frozenset(created))


def _db_edges(repos: list[RepoFacts], stop: frozenset[str]) -> list[Edge]:
    tables = {r.id: _table_refs(r, stop) for r in repos}
    providers = {r.id: {f.value for f in _facts(r, False, FactKind.DB_PROVIDER)} for r in repos}
    linked = _linked_refs(repos)
    df = Counter(name for refs in tables.values() for name in refs.refs)
    creators = Counter(name for refs in tables.values() for name in refs.created)
    edges = []
    for a, b in combinations([r.id for r in repos], 2):
        if _disjoint(linked[a], linked[b]):
            continue  # linked to different Supabase projects: provably different databases
        shared = sorted(set(tables[a].refs) & set(tables[b].refs))
        score = noisy_or(specificity(df[t]) for t in shared) if shared else 0.0
        owned = _owned_by_one_side(shared, tables[a], tables[b])
        if owned == 0 and _disjoint(providers[a], providers[b]):
            continue  # name-only overlap across different DB providers (e.g. Neon vs Supabase)
        sole_owner = any(
            creators[t] == 1 and (t in tables[a].created) != (t in tables[b].created)
            for t in shared
        )
        confidence = _db_tier(db_confidence(score), owned, sole_owner=sole_owner)
        if confidence is None:
            continue
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


def _db_tier(base: Confidence | None, owned: int, *, sole_owner: bool) -> Confidence | None:
    """Spec §16.1: name-only overlap is ambiguous; a single owned table caps at inferred.

    A table that exactly one repo in the workspace creates, queried by the other side, is
    at least inferred however many repos query it: that owner link is what agents need.
    """
    if base is None:
        return None
    if owned == 0:
        return Confidence.AMBIGUOUS
    if owned == 1 and base is Confidence.EXTRACTED:
        return Confidence.INFERRED
    if sole_owner and base is Confidence.AMBIGUOUS:
        return Confidence.INFERRED
    return base


def _db_direction(
    a: str, b: str, shared: list[str], tables: dict[str, _TableRefs]
) -> tuple[str, str]:
    a_created = len(set(shared) & tables[a].created)
    b_created = len(set(shared) & tables[b].created)
    return (b, a) if a_created > b_created else (a, b)


def _linked_refs(repos: list[RepoFacts]) -> dict[str, set[str]]:
    return {
        r.id: {
            f.value
            for f in _facts(r, False, FactKind.DB_PROJECT_REF)
            if not f.value.startswith(_LOCAL_REF)
        }
        for r in repos
    }


def _disjoint(a: set[str], b: set[str]) -> bool:
    """Both sides declare something and nothing matches."""
    return bool(a) and bool(b) and not a & b


def _project_ref_edges(repos: list[RepoFacts]) -> list[Edge]:
    by_ref: dict[str, list[tuple[str, Fact]]] = {}
    for repo in repos:
        for fact in _facts(repo, False, FactKind.DB_PROJECT_REF):
            by_ref.setdefault(fact.value, []).append((repo.id, fact))
    linked = _linked_refs(repos)
    return [
        _edge(
            a_id,
            b_id,
            EdgeType.SHARES_DB,
            Confidence.AMBIGUOUS if ref.startswith(_LOCAL_REF) else Confidence.EXTRACTED,
            0.3 if ref.startswith(_LOCAL_REF) else 1.0,
            [f"db_project_ref:{ref}"],
            (*a_fact.evidence, *b_fact.evidence),
        )
        for ref, members in by_ref.items()
        for (a_id, a_fact), (b_id, b_fact) in combinations(members, 2)
        if not _disjoint(linked[a_id], linked[b_id])
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
