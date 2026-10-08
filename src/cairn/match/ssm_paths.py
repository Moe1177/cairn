"""SSM parameters no IaC creates (spec §25.1): their path often names the service that owns them.

Scripts and pipelines write parameters too (`populate_parameter_store.py`), so nothing in the
workspace creates them. Conventional paths still say whose they are:
`/amplify/${stage}/amplify-${depName}-admin/TABLE` reduces to `/amplify/amplify-admin/table`,
and `amplify-admin` is exactly the serverless service (stack) of one repo. Only an exact match
counts, never a shared word, and the first segment (the app prefix) never does.
"""

from collections import defaultdict
from collections.abc import Sequence
from typing import TYPE_CHECKING

from cairn.detectors.aws_names import clean
from cairn.model.graph import FactKind

if TYPE_CHECKING:
    from cairn.match.matcher import RepoFacts

_MIN_SEGMENTS = 3  # /<app>/<owner>/<name>: anything shorter has no owner segment


def repo_names(repos: Sequence["RepoFacts"]) -> dict[str, str]:
    """Each name (repo id, alias, or the stack it deploys) that points at exactly one repo."""
    owners: dict[str, set[str]] = defaultdict(set)
    for repo in repos:
        names = [repo.id, *repo.aliases]
        names += [
            f.value.split(":", 1)[1]
            for f in repo.contracts.exposes
            if f.kind is FactKind.CLOUD_RESOURCE and f.value.startswith("stack:")
        ]
        for name in names:
            cleaned = clean(name, "stack")
            if cleaned:
                owners[cleaned].add(repo.id)
    return {name: next(iter(ids)) for name, ids in owners.items() if len(ids) == 1}


def path_owner(value: str, user: str, names: dict[str, str]) -> str | None:
    """The one other repo an uncreated `ssm:/app/<owner>/.../name` path names, if any."""
    segments = value.removeprefix("ssm:").strip("/").split("/")
    if len(segments) < _MIN_SEGMENTS:
        return None
    named = {names[s] for s in segments[1:-1] if s in names} - {user}
    return next(iter(named)) if len(named) == 1 else None
