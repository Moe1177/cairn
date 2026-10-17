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
import tempfile
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import ValidationError, field_validator

from cairn.bench.locate_eval import Outcome, summarize
from cairn.errors import CairnError
from cairn.locate.terms import concept_terms, literal_terms
from cairn.model.graph import Frozen
from cairn.org.profile import build_profile, render_profile
from cairn.org.similar import find_similar, render_similar
from cairn.remote.github import GitHub

PRIOR_ART_FILE = "prior_art.yaml"
TERMS_FILE = "agent_terms.yaml"
TERMS_MODEL = "haiku"  # the cheapest model: if it finds the words, any agent will
TERM_COUNT = 3
TERMS_PROMPT = (
    'A developer wants to build: "{task}" Write 3 GitHub code-search queries that would find '
    "an existing implementation of this in other repos. Each query is 1 to 3 words that would "
    "literally appear in such code: class or function names, SDK calls, library names, config "
    "keys. One query per line, nothing else."
)
PROFILE_FILE = "org_profile.md"  # the org's stack as org_profile showed it, kept with the key
PROFILE_TERMS_FILE = "agent_terms_profile.yaml"
PROFILE_TERMS_PROMPT = (
    "The code you'll search belongs to an org whose repos use this stack:\n\n{profile}\n\n"
    + TERMS_PROMPT
)
_LIST_MARK = re.compile(r"^(?:[-*•]|\d+[.)])\s*")
_PREAMBLE = re.compile(r"(?i)^(?:here (?:are|is)|sure|queries)(?=[\s:!,.]|$)")
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


class AgentTerms(Frozen):
    model: str
    generated: str = ""  # YYYY-MM-DD
    prompt: str = ""
    terms: dict[str, tuple[str, ...]]


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


# (client, key, task, how many paths, the terms an agent passed for the task) -> what it found
Locator = Callable[[GitHub, PriorArtSet, PriorArtQuery, int, tuple[str, ...]], Found]


def search_raw(
    client: GitHub, pset: PriorArtSet, query: PriorArtQuery, limit: int, terms: tuple[str, ...]
) -> Found:
    """The task's own words as one code search: what pasting the request in would find."""
    return _search(client, pset, query.task, limit)


def search_terms(
    client: GitHub, pset: PriorArtSet, query: PriorArtQuery, limit: int, terms: tuple[str, ...]
) -> Found:
    """A few of the task's words (code identifiers first), as an agent's first search would."""
    words = list(dict.fromkeys((*literal_terms(query.task), *concept_terms(query.task))))
    return _search(client, pset, " ".join(words[:_SEARCH_TERMS]), limit)


def cairn_similar(
    client: GitHub, pset: PriorArtSet, query: PriorArtQuery, limit: int, terms: tuple[str, ...]
) -> Found:
    """cairn's find_similar with the terms an agent would pass it (see TERMS_FILE)."""
    result = find_similar(client, pset.org, query.task, terms, limit=limit)
    paths = tuple(_org_path(pset.org, hit.repo, hit.path) for hit in result.hits)
    return Found(paths, render_similar(result), result.searches, result.waited)


LOCATORS: dict[str, Locator] = {
    "search-raw": search_raw,
    "search-terms": search_terms,
    "cairn": cairn_similar,
    # The same search, given the terms of an agent that read the org's profile first.
    "cairn-profile": cairn_similar,
}
# Where each term-taking locator's terms are kept beside the key.
TERMS_FILES = {"cairn": TERMS_FILE, "cairn-profile": PROFILE_TERMS_FILE}


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


def load_terms(suite_dir: Path, name: str = TERMS_FILE) -> dict[str, tuple[str, ...]]:
    """The terms an agent passed per task (empty when the suite has none yet)."""
    path = suite_dir / name
    if not path.is_file():
        return {}
    try:
        return AgentTerms.model_validate(yaml.safe_load(path.read_text(encoding="utf-8"))).terms
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise CairnError(f"invalid agent terms {path}: {exc}") from exc


def parse_terms(text: str) -> tuple[str, ...]:
    """A model's answer, one search per line, with its preamble and list marks dropped."""
    found = []
    for raw in text.splitlines():
        line = _LIST_MARK.sub("", raw.strip()).strip().strip("`'\"").strip()
        if not line or line.endswith(":") or _PREAMBLE.match(line) or len(line) > 100:
            continue
        found.append(line)
    return tuple(dict.fromkeys(found))[:TERM_COUNT]


def ask_model_for_terms(
    task: str, model: str = TERMS_MODEL, *, prompt: str = TERMS_PROMPT
) -> tuple[str, ...]:
    """What an agent would pass find_similar for `task`: a headless, isolated `claude -p`."""
    from cairn.bench.runner import ClaudeRunner  # the benchmark's isolated runner

    with tempfile.TemporaryDirectory(prefix="cairn-terms-") as tmp:
        result = ClaudeRunner(model=model, timeout=120).run(
            prompt.replace("{task}", task), Path(tmp), Path(tmp), None
        )
    if result.is_error:
        raise CairnError(f"claude couldn't suggest terms: {result.result_text.strip()[:200]}")
    return parse_terms(result.result_text)


def write_terms(
    suite_dir: Path,
    pset: PriorArtSet,
    ask: Callable[[str], tuple[str, ...]] | None = None,
    *,
    model: str = TERMS_MODEL,
    today: str = "",
    name: str = TERMS_FILE,
    prompt: str = TERMS_PROMPT,
) -> dict[str, tuple[str, ...]]:
    """Ask for terms for every task that has none yet, and save them beside the key: a run is
    then repeatable and free, and the terms are a model's, never hand-tuned to the key."""
    asker = ask or (lambda task: ask_model_for_terms(task, model, prompt=prompt))
    terms = load_terms(suite_dir, name)
    for query in pset.queries:
        if not terms.get(query.id):
            terms[query.id] = asker(query.task)
    ordered = {q.id: terms[q.id] for q in pset.queries}
    doc = AgentTerms(model=model, generated=today, prompt=prompt, terms=ordered)
    source = "the task alone" if prompt == TERMS_PROMPT else f"the task and {PROFILE_FILE}"
    header = (
        "# What an agent passes find_similar for each task in prior_art.yaml: written by a model\n"
        f"# from {source} (cairn bench-prior-art --make-terms), never edited by hand.\n"
    )
    body = yaml.safe_dump(doc.model_dump(), sort_keys=False, width=100, allow_unicode=True)
    (suite_dir / name).write_text(header + body, encoding="utf-8", newline="\n")
    return ordered


def suite_terms(
    suite_dir: Path,
    pset: PriorArtSet,
    locators: Sequence[str],
    *,
    make: bool = False,
    today: str = "",
) -> dict[str, dict[str, tuple[str, ...]]]:
    """Each term-taking locator's terms per task: read from beside the key, or with `make`
    asked for first where missing (cairn-profile's agent reads the suite's PROFILE_FILE)."""
    found = {}
    for name in locators:
        if name not in TERMS_FILES:
            continue
        if not make:
            found[name] = load_terms(suite_dir, TERMS_FILES[name])
            continue
        prompt = TERMS_PROMPT if name == "cairn" else _profile_prompt(suite_dir)
        found[name] = write_terms(
            suite_dir, pset, today=today, name=TERMS_FILES[name], prompt=prompt
        )
    return found


def _profile_prompt(suite_dir: Path) -> str:
    path = suite_dir / PROFILE_FILE
    try:
        profile = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise CairnError(f"no {path}: build it first with --make-profile") from exc
    return PROFILE_TERMS_PROMPT.replace("{profile}", profile)


def write_profile(suite_dir: Path, client: GitHub, pset: PriorArtSet) -> str:
    """Read the org's profile over the API and keep the text an agent saw beside the key, so
    the terms made from it can be checked and the run repeated."""
    text = render_profile(build_profile(client, pset.org, pset.host))
    (suite_dir / PROFILE_FILE).write_text(text + "\n", encoding="utf-8", newline="\n")
    return text


def evaluate(
    client: GitHub,
    pset: PriorArtSet,
    locators: Sequence[str],
    *,
    terms: Mapping[str, tuple[str, ...]] | None = None,
    limit: int = 10,
    registry: dict[str, Locator] | None = None,
    terms_by_locator: Mapping[str, Mapping[str, tuple[str, ...]]] | None = None,
) -> list[PriorArtOutcome]:
    return list(
        iter_outcomes(
            client,
            pset,
            locators,
            terms=terms,
            limit=limit,
            registry=registry,
            terms_by_locator=terms_by_locator,
        )
    )


def iter_outcomes(
    client: GitHub,
    pset: PriorArtSet,
    locators: Sequence[str],
    *,
    terms: Mapping[str, tuple[str, ...]] | None = None,
    limit: int = 10,
    registry: dict[str, Locator] | None = None,
    terms_by_locator: Mapping[str, Mapping[str, tuple[str, ...]]] | None = None,
) -> Iterator[PriorArtOutcome]:
    """Each task's outcome as soon as it is scored, so a run that fails late keeps the rest.
    A locator's own terms (terms_by_locator) win over the shared `terms`."""
    chosen = registry or LOCATORS
    own = terms_by_locator or {}
    for query in pset.queries:
        for name in locators:
            given = own.get(name, terms or {})
            started = time.perf_counter()
            found = chosen[name](client, pset, query, limit, given.get(query.id, ()))
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
