"""Locate across several repos: each repo's answer, merged into one list."""

from collections.abc import Mapping
from dataclasses import replace

from cairn.locate.model import LocateHit, LocateResult


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
