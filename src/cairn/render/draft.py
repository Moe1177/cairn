"""A repo's draft summary, until someone writes one: what kind of repo it is, from what cairn
detected (routes, tables, topics, deploys, who depends on it).

Built only from counts and cairn's own words, never from repo text (spec §20.1): INDEX is loaded
into every agent session, so a README, package name or topic name can't reach it this way.
"""

from collections import Counter

from cairn.model.graph import Confidence, EdgeType, Fact, FactKind, Repo, Workspace

DRAFT_LABEL = "draft"
_WEB = frozenset({"nextjs", "react", "vue", "svelte", "nuxt", "angular", "astro", "remix"})
_DETAILS = 3
# One route or one resource is as likely a test fixture or an example as what the repo is for.
_MINIMUM = {FactKind.HTTP_ROUTE: 2, FactKind.CLOUD_RESOURCE: 2}


def draft_summary(repo: Repo, workspace: Workspace) -> str | None:
    """`web app (104 routes, owns 46 tables)`, or None when cairn found nothing to say."""
    # A topic counts once it links to another repo: alone it's often a test fixture's.
    pubsub = _linked(repo.id, workspace, EdgeType.PUBSUB, outgoing=True) + _linked(
        repo.id, workspace, EdgeType.PUBSUB, outgoing=False
    )
    exposes = _counts(repo.contracts.exposes, topics=bool(pubsub))
    consumes = _counts(repo.contracts.consumes, topics=bool(pubsub))
    deploys = _linked(repo.id, workspace, EdgeType.DEPLOYS, outgoing=True)
    dependents = _linked(repo.id, workspace, EdgeType.DEPENDS_ON_PACKAGE, outgoing=False)
    role = _role(repo, exposes, consumes, deploys=deploys, dependents=dependents)
    if role is None:
        return None
    details = _details(exposes, consumes, deploys=deploys, dependents=dependents)[:_DETAILS]
    return f"{role} ({', '.join(details)})" if details else role


def _role(
    repo: Repo,
    exposes: Counter[FactKind],
    consumes: Counter[FactKind],
    *,
    deploys: int,
    dependents: int,
) -> str | None:
    serves = exposes[FactKind.HTTP_ROUTE] or exposes[FactKind.GRPC_SERVICE]
    if deploys:
        return "deploy config"
    if serves and _WEB & set(repo.stack):
        return "web app"
    if serves:
        return "service"
    if any(f.value.startswith("lambda:") for f in repo.contracts.exposes):
        return "serverless service"
    if exposes[FactKind.CLI]:
        return "command-line tool"
    if consumes[FactKind.TOPIC] or exposes[FactKind.TOPIC]:
        return "worker"
    if dependents:
        return "library"
    if exposes[FactKind.CLOUD_RESOURCE]:
        return "infrastructure"
    return None  # the stack alone is on the line already


def _details(
    exposes: Counter[FactKind],
    consumes: Counter[FactKind],
    *,
    deploys: int,
    dependents: int,
) -> list[str]:
    found = [
        _count(deploys, "repo", "deploys"),
        _count(exposes[FactKind.HTTP_ROUTE], "route"),
        _count(exposes[FactKind.GRPC_SERVICE], "gRPC service"),
        _count(exposes[FactKind.DB_TABLE], "table", "owns"),
        _count(exposes[FactKind.TOPIC], "topic", "publishes"),
        _count(consumes[FactKind.TOPIC], "topic", "consumes"),
        _count(exposes[FactKind.CLOUD_RESOURCE], "AWS resource", "creates"),
        _count(dependents, "repo", "used as a package by"),
    ]
    return [d for d in found if d]


def _counts(facts: tuple[Fact, ...], *, topics: bool) -> Counter[FactKind]:
    """Facts per kind, leaving out kinds seen fewer times than their minimum."""
    found = Counter(f.kind for f in facts if topics or f.kind is not FactKind.TOPIC)
    return Counter({k: n for k, n in found.items() if n >= _MINIMUM.get(k, 1)})


def _linked(repo_id: str, workspace: Workspace, type_: EdgeType, *, outgoing: bool) -> int:
    """Distinct repos joined to this one by confirmed or inferred links of `type_`."""
    others = {
        e.target if outgoing else e.source
        for e in workspace.edges
        if e.type is type_
        and e.confidence.rank >= Confidence.INFERRED.rank
        and (e.source if outgoing else e.target) == repo_id
    }
    return len(others)


def _count(n: int, noun: str, verb: str = "") -> str:
    if not n:
        return ""
    text = f"{n} {noun}{'' if n == 1 else 's'}"
    return f"{verb} {text}" if verb else text
