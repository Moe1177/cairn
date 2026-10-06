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


def names_repo(hint: str, repo: "RepoFacts", distinctive: frozenset[str] | None = None) -> bool:
    wanted = tokens(hint)
    if distinctive is not None:
        wanted &= distinctive
    return any(wanted & tokens(name) for name in (repo.id, *repo.aliases))


def distinctive_tokens(repos: Sequence["RepoFacts"]) -> frozenset[str]:
    """Name words that point at exactly one repo. A company prefix (`acme` in every
    @acme/* package) names everything, so it names nothing."""
    owners: dict[str, set[str]] = defaultdict(set)
    for repo in repos:
        for name in (repo.id, *repo.aliases):
            for token in tokens(name):
                owners[token].add(repo.id)
    return frozenset(t for t, ids in owners.items() if len(ids) == 1)


def http_edges(repos: Sequence["RepoFacts"]) -> list[Edge]:
    """Consumer → exposer for each called route template another repo serves (spec §21.1)."""
    code: dict[str, list[tuple[RepoFacts, tuple[Evidence, ...]]]] = defaultdict(list)
    specs: dict[str, list[tuple[RepoFacts, tuple[Evidence, ...]]]] = defaultdict(list)
    for repo in repos:
        for fact in repo.contracts.exposes:
            if fact.kind is FactKind.HTTP_ROUTE and not is_generic(fact.value):
                spec_only = "source:openapi" in fact.hints and "source:code" not in fact.hints
                (specs if spec_only else code)[fact.value].append((repo, fact.evidence))
    distinctive = distinctive_tokens(repos)
    found: dict[tuple[str, str], _Link] = {}
    for caller in repos:
        for fact in caller.contracts.consumes:
            if fact.kind is not FactKind.HTTP_ROUTE or is_generic(fact.value):
                continue
            # Code that serves a route outranks an OpenAPI file merely describing it.
            routes = code.get(fact.value) or specs.get(fact.value, [])
            named = _named_repos(fact.hints, repos, distinctive)
            serves_itself = any(r.id == caller.id for r, _ in routes)
            if serves_itself:
                # Most likely a call to itself, unless the base URL names another server
                # (a gateway proxying /trips/:id to trips-svc).
                routes = [(r, ev) for r, ev in routes if r.id in named and r.id != caller.id]
            else:
                routes = [(r, ev) for r, ev in routes if r.id != caller.id]
            for (owner, served), confidence in _resolve(routes, named):
                link = found.setdefault((caller.id, owner.id), _Link(EdgeType.CALLS_HTTP))
                link.add(confidence, f"http_route:{fact.value}", (*fact.evidence, *served))
    return [link.edge(source, target) for (source, target), link in sorted(found.items())]


def _named_repos(
    hints: Iterable[str], repos: Sequence["RepoFacts"], distinctive: frozenset[str]
) -> set[str]:
    service_hints = [h for h in hints if not h.startswith("source:")]
    return {r.id for r in repos if any(names_repo(h, r, distinctive) for h in service_hints)}


def _resolve(
    owners: list[tuple["RepoFacts", tuple[Evidence, ...]]], named: set[str]
) -> list[tuple[tuple["RepoFacts", tuple[Evidence, ...]], Confidence]]:
    if not owners:
        return []
    matching = [o for o in owners if o[0].id in named]
    if named and not matching:
        # The base URL names a different repo than the one serving the route: don't guess.
        return [(o, Confidence.AMBIGUOUS) for o in owners]
    if len(owners) == 1:
        return [(owners[0], Confidence.EXTRACTED if matching else Confidence.INFERRED)]
    if len(matching) == 1:  # several services serve it; the base URL names one of them
        return [(matching[0], Confidence.INFERRED)]
    return [(o, Confidence.AMBIGUOUS) for o in owners]


def host_edges(repos: Sequence["RepoFacts"]) -> list[Edge]:
    """Spec §24: a call addressed to a host named exactly like another repo (service DNS)."""
    found: dict[tuple[str, str], _Link] = {}
    for caller in repos:
        for fact in caller.contracts.consumes:
            if fact.kind is not FactKind.SERVICE_HOST:
                continue
            named = [r for r in repos if fact.value in {n.lower() for n in (r.id, *r.aliases)}]
            if len(named) != 1 or named[0].id == caller.id:
                continue
            link = found.setdefault((caller.id, named[0].id), _Link(EdgeType.CALLS_HTTP))
            link.add(Confidence.INFERRED, f"host:{fact.value}", fact.evidence)
    return [link.edge(source, target) for (source, target), link in sorted(found.items())]


def compose_edges(repos: Sequence["RepoFacts"]) -> list[Edge]:
    """Spec §21.2: `depends_on` between two services built from (or named after) repos."""
    found: dict[tuple[str, str], _Link] = {}
    for holder in repos:
        for fact in holder.contracts.consumes:
            if fact.kind is not FactKind.COMPOSE_SERVICE or "=>" not in fact.value:
                continue
            source_ref, target_ref = fact.value.split("=>", 1)
            source, target = _compose_repo(source_ref, repos), _compose_repo(target_ref, repos)
            if source and target and source.id != target.id:
                link = found.setdefault((source.id, target.id), _Link(EdgeType.COMPOSE_LINK))
                link.add(Confidence.EXTRACTED, "compose:depends_on", fact.evidence)
    return [link.edge(source, target) for (source, target), link in sorted(found.items())]


def _compose_repo(ref: str, repos: Sequence["RepoFacts"]) -> "RepoFacts | None":
    kind, _, value = ref.partition(":")
    if kind == "path":
        owners = [r for r in repos if value == r.path or value.startswith(f"{r.path}/")]
        return max(owners, key=lambda r: len(r.path), default=None)
    if kind == "image":
        named = [r for r in repos if value in {n.lower() for n in (r.id, *r.aliases)}]
        return named[0] if len(named) == 1 else None
    return None


def grpc_edges(repos: Sequence["RepoFacts"]) -> list[Edge]:
    """Client → implementer of a gRPC service (spec §21.2)."""
    return _provider_edges(
        repos, FactKind.GRPC_SERVICE, EdgeType.GRPC, "grpc", consumer_to_provider=True
    )


def pubsub_edges(repos: Sequence["RepoFacts"]) -> list[Edge]:
    """Publisher → subscriber of a topic (spec §21.2)."""
    return _provider_edges(
        repos, FactKind.TOPIC, EdgeType.PUBSUB, "topic", consumer_to_provider=False
    )


def _provider_edges(
    repos: Sequence["RepoFacts"],
    kind: FactKind,
    edge_type: EdgeType,
    label: str,
    *,
    consumer_to_provider: bool,
) -> list[Edge]:
    providers: dict[str, list[tuple[RepoFacts, tuple[Evidence, ...]]]] = defaultdict(list)
    for repo in repos:
        for fact in repo.contracts.exposes:
            if fact.kind is kind:
                providers[fact.value].append((repo, fact.evidence))
    found: dict[tuple[str, str], _Link] = {}
    for consumer in repos:
        for fact in consumer.contracts.consumes:
            if fact.kind is not kind:
                continue
            owners = providers.get(fact.value, [])
            if any(r.id == consumer.id for r, _ in owners):
                continue  # it provides this itself
            confidence = Confidence.INFERRED if len(owners) == 1 else Confidence.AMBIGUOUS
            for owner, provided in owners:
                pair = (consumer.id, owner.id) if consumer_to_provider else (owner.id, consumer.id)
                link = found.setdefault(pair, _Link(edge_type))
                link.add(confidence, f"{label}:{fact.value}", (*provided, *fact.evidence))
    return [link.edge(source, target) for (source, target), link in sorted(found.items())]


def env_edges(repos: Sequence["RepoFacts"]) -> list[Edge]:
    """Spec §21.3: repos reading the same specific env var. Always ambiguous on its own; it
    only ever gets promoted by corroboration from a real link between the same pair."""
    names = {
        r.id: {f.value: f.evidence for f in r.contracts.consumes if f.kind is FactKind.ENV_VAR_NAME}
        for r in repos
    }
    df: dict[str, int] = defaultdict(int)
    for found in names.values():
        for name in found:
            df[name] += 1
    too_common = len(repos) >= 4
    edges: list[Edge] = []
    ordered = sorted(repos, key=lambda r: r.id)
    for i, a in enumerate(ordered):
        for b in ordered[i + 1 :]:
            shared = sorted(
                n
                for n in names[a.id].keys() & names[b.id].keys()
                if not (too_common and df[n] * 2 > len(repos))
            )
            if not shared:
                continue
            evidence = [ev for n in shared[:3] for ev in (*names[a.id][n][:1], *names[b.id][n][:1])]
            link = _Link(EdgeType.SHARES_ENV)
            for name in shared:
                link.add(Confidence.AMBIGUOUS, f"env:{name}", ())
            link.evidence = evidence
            edges.append(link.edge(a.id, b.id))
    return edges


class _Link:
    def __init__(self, edge_type: EdgeType) -> None:
        self.type = edge_type
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
            type=self.type,
            confidence=self.confidence,
            score=_SCORES[self.confidence],
            signals=tuple(dict.fromkeys(self.signals)),
            evidence=tuple(self.evidence[:MAX_EVIDENCE]),
        )
