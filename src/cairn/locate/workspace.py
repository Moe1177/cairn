"""Locate across several repos: each repo's answer, merged into one list."""

import re
from collections.abc import Callable, Mapping
from dataclasses import replace

from cairn.locate.model import LocateHit, LocateResult
from cairn.model.graph import Confidence, Workspace


def fan_out(results: Mapping[str, LocateResult], *, limit: int = 10) -> tuple[LocateHit, ...]:
    """Every repo's hits tagged with the repo, ordered by rank within its repo, then score:
    each repo's best answer comes before any repo's second best."""
    ranked = [
        (position, -hit.score, repo, replace(hit, repo=repo))
        for repo, result in results.items()
        for position, hit in enumerate(result.hits)
    ]
    ranked.sort(key=lambda entry: entry[:3])
    return tuple(hit for *_, hit in ranked[:limit])


NAMED_MAX = 4
RELATED_MAX = 5


def named_repos(workspace: Workspace, asked: str, question: str) -> list[str]:
    """Other repos the question names by id or alias, as whole words."""
    text = question[:4000].lower()
    found = []
    for repo in workspace.repos:
        if repo.id == asked:
            continue
        names = (repo.id.lower(), *(a.lower() for a in repo.aliases))
        if any(re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-])", text) for n in names if n):
            found.append(repo.id)
    return found[:NAMED_MAX]


def related_repos(workspace: Workspace, asked: str, exclude: set[str]) -> list[str]:
    """The repos the map links to `asked` (unconfirmed links left out), strongest first."""
    edges = sorted(
        (e for e in workspace.edges_for(asked) if e.confidence is not Confidence.AMBIGUOUS),
        key=lambda e: (-e.confidence.rank, -e.score, e.key),
    )
    found: list[str] = []
    for edge in edges:
        other = edge.target if edge.source == asked else edge.source
        if other not in exclude and other not in found and workspace.repo(other) is not None:
            found.append(other)
    return found[:RELATED_MAX]


def scoped_locate(
    workspace: Workspace | None,
    asked: str,
    question: str,
    run: Callable[[list[str]], dict[str, LocateResult]],
) -> tuple[dict[str, LocateResult], list[str], list[str]]:
    """(results by repo, named repos, related repos searched). The asked repo and repos the
    question names first; the related repos too unless a literal (an identifier, route or
    message) already answered: cross-repo questions rarely name the other repo, and the asked
    repo nearly always has a few loose word matches."""
    named = named_repos(workspace, asked, question) if workspace is not None else []
    results = run([asked, *named])
    if workspace is None or any(_literal_answer(r) for r in results.values()):
        return results, named, []
    related = related_repos(workspace, asked, exclude={asked, *named})
    results.update(run(related) if related else {})
    return results, named, related


def _literal_answer(result: LocateResult) -> bool:
    return bool(result.hits) and "literal:" in result.reason
