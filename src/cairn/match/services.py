"""Edges between services (spec §21): HTTP calls (and, in later tasks, gRPC, pub/sub, compose, env).

Kept apart from matcher.py so each module stays small. Every function takes the matcher's
RepoFacts and returns Edges; precision before recall: unclear evidence stays `ambiguous`.
"""

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING

from cairn.detectors.http_paths import is_generic
from cairn.model.graph import MAX_EVIDENCE, Confidence, Edge, EdgeType, Evidence, FactKind

if TYPE_CHECKING:
    from cairn.match.matcher import RepoFacts

_SCORES = {Confidence.EXTRACTED: 1.0, Confidence.INFERRED: 0.6, Confidence.AMBIGUOUS: 0.2}
# Words in repo names and env vars that don't identify a service.
_FILLER = frozenset(
    {
        "svc",
        "service",
        "services",
        "api",
        "app",
        "web",
        "server",
        "backend",
        "frontend",
        "client",
        "core",
        "lib",
        "url",
        "uri",
        "host",
        "addr",
        "address",
        "base",
        "endpoint",
        "http",
        "https",
        "port",
        "internal",
        "public",
        "next",
        "the",
    }
)


def tokens(text: str) -> frozenset[str]:
    """Identifying words: `TRIPS_SVC_URL` and `trips-svc` both give {"trips"}."""
    return frozenset(
        t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) >= 3 and t not in _FILLER
    )


def names_repo(hint: str, repo: "RepoFacts") -> bool:
    wanted = tokens(hint)
    return any(wanted & tokens(name) for name in (repo.id, *repo.aliases))


def http_edges(repos: Sequence["RepoFacts"]) -> list[Edge]:
    """Consumer → exposer for each called route template another repo serves (spec §21.1)."""
    servers: dict[str, list[tuple[RepoFacts, tuple[Evidence, ...]]]] = defaultdict(list)
    for repo in repos:
        for fact in repo.contracts.exposes:
            if fact.kind is FactKind.HTTP_ROUTE and not is_generic(fact.value):
                servers[fact.value].append((repo, fact.evidence))
    found: dict[tuple[str, str], _Link] = {}
    for caller in repos:
        for fact in caller.contracts.consumes:
            if fact.kind is not FactKind.HTTP_ROUTE or is_generic(fact.value):
                continue
            routes = servers.get(fact.value, [])
            if any(r.id == caller.id for r, _ in routes):
                continue  # it serves this route itself: most likely a call to itself
            for (owner, served), confidence in _resolve(routes, fact.hints):
                link = found.setdefault((caller.id, owner.id), _Link())
                link.add(confidence, f"http_route:{fact.value}", (*fact.evidence, *served))
    return [link.edge(source, target) for (source, target), link in sorted(found.items())]


def _resolve(
    owners: list[tuple["RepoFacts", tuple[Evidence, ...]]], hints: Iterable[str]
) -> list[tuple[tuple["RepoFacts", tuple[Evidence, ...]], Confidence]]:
    if not owners:
        return []
    named = [o for o in owners if any(names_repo(h, o[0]) for h in hints)]
    if len(owners) == 1:
        return [(owners[0], Confidence.EXTRACTED if named else Confidence.INFERRED)]
    if len(named) == 1:  # several services serve it; the base URL names one of them
        return [(named[0], Confidence.INFERRED)]
    return [(o, Confidence.AMBIGUOUS) for o in owners]


class _Link:
    def __init__(self) -> None:
        self.confidence = Confidence.AMBIGUOUS
        self.signals: list[str] = []
        self.evidence: list[Evidence] = []

    def add(self, confidence: Confidence, signal: str, evidence: Iterable[Evidence]) -> None:
        if confidence.rank > self.confidence.rank:
            self.confidence = confidence
        self.signals.append(signal)
        self.evidence += [ev for ev in evidence if ev not in self.evidence]

    def edge(self, source: str, target: str) -> Edge:
        return Edge(
            source=source,
            target=target,
            type=EdgeType.CALLS_HTTP,
            confidence=self.confidence,
            score=_SCORES[self.confidence],
            signals=tuple(dict.fromkeys(self.signals)),
            evidence=tuple(self.evidence[:MAX_EVIDENCE]),
        )
