"""Render Blueprint edges (spec §26.3): deploys, and services reading each other's address.

A blueprint service belongs to the repo its `repo:` URL names (when that is exactly one sibling)
or else to the blueprint's own repo. The blueprint's repo deploys every service whose code lives
in a sibling. A `fromService` reference links the reading service's repo to the read service's
repo: an address (host, hostport, port) is a call; copying an env var is a use. All of these are
explicit configuration, so they are extracted; a service name two blueprints define is no one's.
"""

from collections import defaultdict
from collections.abc import Sequence
from typing import TYPE_CHECKING

from cairn.model.graph import MAX_EVIDENCE, Confidence, Edge, EdgeType, Evidence, FactKind

if TYPE_CHECKING:
    from cairn.match.matcher import RepoFacts

_ADDRESSES = frozenset({"host", "hostport", "port"})


def render_edges(repos: Sequence["RepoFacts"]) -> list[Edge]:
    owners, deploys = _owners(repos)
    found: dict[tuple[str, str, EdgeType], tuple[list[str], list[Evidence]]] = {}
    for blueprint, target, signal, evidence in deploys:
        _add(found, (blueprint, target, EdgeType.DEPLOYS), signal, evidence)
    for repo in repos:
        for fact in repo.contracts.consumes:
            if fact.kind is not FactKind.PLATFORM_SERVICE or not fact.value.startswith("render:"):
                continue
            reader, _, target = fact.value.removeprefix("render:").partition(">")
            caller = owners.get(f"render:{reader}")
            callee = owners.get(f"render:{target}")
            if not (target and caller and callee) or caller == callee:
                continue
            props = [h.removeprefix("property:") for h in fact.hints if h.startswith("property:")]
            address = any(p in _ADDRESSES for p in props)
            type_ = EdgeType.CALLS_HTTP if address else EdgeType.USES_RESOURCE
            for prop in props:
                _add(found, (caller, callee, type_), f"render:{target}.{prop}", fact.evidence)
    return [
        Edge(
            source=source,
            target=target,
            type=type_,
            confidence=Confidence.EXTRACTED,
            score=1.0,
            signals=tuple(dict.fromkeys(signals)),
            evidence=tuple(dict.fromkeys(evidence))[:MAX_EVIDENCE],
        )
        for (source, target, type_), (signals, evidence) in sorted(found.items())
    ]


def _owners(
    repos: Sequence["RepoFacts"],
) -> tuple[dict[str, str], list[tuple[str, str, str, tuple[Evidence, ...]]]]:
    """Service -> the repo holding its code, and (blueprint, code repo) deploy pairs."""
    names = _repo_names(repos)
    claims: dict[str, set[str]] = defaultdict(set)
    deploys = []
    for repo in repos:
        for fact in repo.contracts.exposes:
            if fact.kind is not FactKind.PLATFORM_SERVICE or not fact.value.startswith("render:"):
                continue
            source = _hint(fact.hints, "repo:")
            code_repo = names.get(source, repo.id) if source else repo.id
            if source and source not in names and source != repo.id.lower():
                continue  # its code lives outside the workspace
            claims[fact.value].add(code_repo)
            if code_repo != repo.id:
                deploys.append((repo.id, code_repo, f"render_repo:{source}", fact.evidence))
    owners = {service: next(iter(ids)) for service, ids in claims.items() if len(ids) == 1}
    return owners, deploys


def _repo_names(repos: Sequence["RepoFacts"]) -> dict[str, str]:
    seen: dict[str, set[str]] = defaultdict(set)
    for repo in repos:
        for name in (repo.id, *repo.aliases):
            seen[name.lower()].add(repo.id)
    return {name: next(iter(ids)) for name, ids in seen.items() if len(ids) == 1}


def _hint(hints: tuple[str, ...], prefix: str) -> str | None:
    return next((h[len(prefix) :] for h in hints if h.startswith(prefix)), None)


def _add(
    found: dict[tuple[str, str, EdgeType], tuple[list[str], list[Evidence]]],
    key: tuple[str, str, EdgeType],
    signal: str,
    evidence: tuple[Evidence, ...],
) -> None:
    signals, gathered = found.setdefault(key, ([], []))
    signals.append(signal)
    gathered += [ev for ev in evidence if ev not in gathered]
