"""The offline prior-art benchmark: given a feature to build, does a locator find the org's
existing implementation of it, and how fast? No agent, no clone, no cost beyond API calls.

Each suite's `prior_art.yaml` names a GitHub org and lists feature tasks with the files that
already implement them (found and read by hand, never taken from a locator's output). Every
locator answers every task over the host's API; it is scored on where the first answer file
lands (hit@k, MRR), how much text it returns, and how long it takes.

An org has thousands of repos, so a key can't list every implementation: a locator may surface
a valid one nobody judged. `rejected` lists files judged not to answer, and the report says what
share of each locator's top five was judged, so an unjudged hit reads as unknown, not as wrong.
Judge those (add them to `answers` or `rejected`) and the numbers firm up, run by run.
"""

import json
import re
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import ValidationError, field_validator

from cairn.bench.locate_eval import Outcome, summarize
from cairn.errors import CairnError
from cairn.locate.terms import concept_terms, literal_terms
from cairn.model.graph import Frozen
from cairn.remote.github import GitHub

PRIOR_ART_FILE = "prior_art.yaml"
TOP = 5
_SEARCH_TERMS = 3  # code search ANDs its terms: more than a few rarely all appear in one file
_ORG = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")  # also keeps it out of the query


class PriorArtQuery(Frozen):
    id: str
    category: Literal["literal", "vocabulary", "broad"]
    task: str  # the feature, as a developer would ask for it
    answers: tuple[str, ...]  # repo/path in the org: any one counts as found
    rejected: tuple[str, ...] = ()  # judged: these don't implement the task
    note: str = ""

    @field_validator("answers", "rejected")
    @classmethod
    def _org_paths(cls, paths: tuple[str, ...]) -> tuple[str, ...]:
        if any("/" not in p or p.startswith("/") or ".." in p.split("/") for p in paths):
            raise ValueError("paths must be repo/path inside the org")
        return paths


class PriorArtSet(Frozen):
    host: str = "github.com"
    org: str
    split: Literal["dev", "held"]
    queries: tuple[PriorArtQuery, ...]

    @field_validator("org")
    @classmethod
    def _org_name(cls, org: str) -> str:
        if not _ORG.fullmatch(org):
            raise ValueError("org must be a GitHub org or user name")
        return org

    @field_validator("queries")
    @classmethod
    def _answered(cls, queries: tuple[PriorArtQuery, ...]) -> tuple[PriorArtQuery, ...]:
        if any(not q.answers for q in queries):
            raise ValueError("every task needs at least one answer file")
        return queries


@dataclass(frozen=True)
class Found:
    paths: tuple[str, ...]  # repo/path, best first
    text: str  # what an agent would read
    searches: int
    waited: float = 0.0


@dataclass(frozen=True)
class PriorArtOutcome(Outcome):
    top: tuple[str, ...] = ()  # the first TOP paths
    unjudged: tuple[str, ...] = ()  # those the key neither accepts nor rejects: judge them
    searches: int = 0
    waited: float = 0.0


Locator = Callable[[GitHub, PriorArtSet, PriorArtQuery, int], Found]


def search_raw(client: GitHub, pset: PriorArtSet, query: PriorArtQuery, limit: int) -> Found:
    """The task's own words as one code search: what pasting the request in would find."""
    return _search(client, pset, query.task, limit)


def search_terms(client: GitHub, pset: PriorArtSet, query: PriorArtQuery, limit: int) -> Found:
    """A few of the task's words (code identifiers first), as an agent's first search would."""
    terms = list(dict.fromkeys((*literal_terms(query.task), *concept_terms(query.task))))
    return _search(client, pset, " ".join(terms[:_SEARCH_TERMS]), limit)


LOCATORS: dict[str, Locator] = {"search-raw": search_raw, "search-terms": search_terms}


def _search(client: GitHub, pset: PriorArtSet, words: str, limit: int) -> Found:
    page = client.search_code(f"{words} org:{pset.org}", per_page=limit)
    paths = tuple(_org_path(pset.org, hit.repo, hit.path) for hit in page.hits)
    lines = [
        f"- {path} {' … '.join(' '.join(f.split()) for f in hit.fragments)[:300]}".rstrip()
        for path, hit in zip(paths, page.hits, strict=True)
    ]
    return Found(paths, "\n".join(lines), 1, page.waited)


def _org_path(org: str, repo: str, path: str) -> str:
    owner, _, name = repo.partition("/")
    return f"{name}/{path}" if owner.lower() == org.lower() else f"{repo}/{path}"


def load_prior_art_set(suite_dir: Path) -> PriorArtSet:
    path = suite_dir / PRIOR_ART_FILE
    try:
        return PriorArtSet.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise CairnError(f"invalid prior-art key {path}: {exc}") from exc


def key_problems(client: GitHub, pset: PriorArtSet) -> list[str]:
    """Answer files that aren't on their repo's default branch any more (what search sees)."""
    problems = []
    for query in pset.queries:
        for answer in query.answers:
            repo, _, path = answer.partition("/")
            try:
                if not client.file_exists(f"{pset.org}/{repo}", path):
                    problems.append(f"{query.id}: no file {answer} in {pset.org}")
            except CairnError as exc:  # a repo renamed or moved, say
                problems.append(f"{query.id}: {exc}")
    return problems


def evaluate(
    client: GitHub,
    pset: PriorArtSet,
    locators: Sequence[str],
    *,
    limit: int = 10,
    registry: dict[str, Locator] | None = None,
) -> list[PriorArtOutcome]:
    return list(iter_outcomes(client, pset, locators, limit=limit, registry=registry))


def iter_outcomes(
    client: GitHub,
    pset: PriorArtSet,
    locators: Sequence[str],
    *,
    limit: int = 10,
    registry: dict[str, Locator] | None = None,
) -> Iterator[PriorArtOutcome]:
    """Each task's outcome as soon as it is scored, so a run that fails late keeps the rest."""
    chosen = registry or LOCATORS
    for query in pset.queries:
        for name in locators:
            started = time.perf_counter()
            found = chosen[name](client, pset, query, limit)
            # Wall time minus rate-limit waits: the waits depend on what ran before, not on
            # the locator (they are reported on their own).
            ms = (time.perf_counter() - started) * 1000 - found.waited * 1000
            yield _outcome(pset, query, name, found, ms)


def _outcome(
    pset: PriorArtSet, query: PriorArtQuery, name: str, found: Found, ms: float
) -> PriorArtOutcome:
    answers = {a.lower() for a in query.answers}
    judged = answers | {r.lower() for r in query.rejected}
    paths = [p.lower() for p in found.paths]
    rank = next((i + 1 for i, p in enumerate(paths) if p in answers), None)
    top = found.paths[:TOP]
    return PriorArtOutcome(
        query_id=query.id,
        split=pset.split,
        category=query.category,
        mode=name,
        route=pset.org,
        rank=rank,
        recall_at_5=len({p.lower() for p in top} & answers) / len(answers),
        tokens=-(-len(found.text) // 4),
        ms=round(max(ms, 0.0), 2),
        top=top,
        unjudged=tuple(p for p in top if p.lower() not in judged),
        searches=found.searches,
        waited=round(found.waited, 2),
    )


def report(outcomes: Iterable[PriorArtOutcome]) -> str:
    rows = list(outcomes)
    lines = [summarize(rows).split("\nHybrid routing")[0].rstrip(), ""]
    lines += [
        "Judged share of each top five (lower: more hits nobody has checked yet):",
        "",
        "| split | locator | judged@5 | searches/task | rate-limit wait (s) |",
        "|---|---|---|---|---|",
    ]
    for split in sorted({o.split for o in rows}, key=["dev", "held"].index):
        for mode in dict.fromkeys(o.mode for o in rows):
            group = [o for o in rows if o.split == split and o.mode == mode]
            n = len(group)
            lines.append(
                f"| {split} | {mode} | {sum(map(judged_at_5, group)) / n:.2f} | "
                f"{sum(o.searches for o in group) / n:.1f} | {sum(o.waited for o in group):.0f} |"
            )
    unjudged = sum(len(o.unjudged) for o in rows)
    if unjudged:
        lines += [
            "",
            f"{unjudged} hits in a top five are unjudged: each outcome's `unjudged` in the JSON "
            "lists them, to add to the key's answers or rejected.",
        ]
    return "\n".join(lines) + "\n"


def judged_at_5(outcome: PriorArtOutcome) -> float:
    """Share of the top five the key has judged (1.0 when nothing came back)."""
    if not outcome.top:
        return 1.0
    return 1 - len(outcome.unjudged) / len(outcome.top)


def outcomes_json(outcomes: Iterable[PriorArtOutcome]) -> str:
    return json.dumps([o.__dict__ for o in outcomes], indent=1)
