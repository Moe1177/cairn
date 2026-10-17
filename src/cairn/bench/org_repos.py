"""The org-repos benchmark: from a phrase ("the terraform provider for AWS"), which locator finds
the org repo it means, and how fast? For repos an agent can't see because nobody cloned them.

Each suite's `repos.yaml` lists phrases with the active repos they mean, written from what each
product does without reading the org's listing. Two locators answer:

- **cairn**: `resolve_repo`'s org catalog, from the listing kept beside the key
  (`org_catalog.json`, made with --make-catalog, so a run is repeatable);
- **github-search**: GitHub's repository search, live, with the short query an agent would type
  (written by a model from the phrase, kept in `agent_repo_queries.yaml`, never edited).
"""

import json
import re
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import ValidationError

from cairn.bench.prior_art import TERMS_MODEL
from cairn.errors import CairnError
from cairn.model.graph import Frozen
from cairn.org.catalog import (
    CatalogIndex,
    OrgCatalog,
    build_catalog,
    find_repos,
    load_catalog,
    save_catalog,
)
from cairn.remote.github import GitHub

REPOS_FILE = "repos.yaml"
CATALOG_FILE = "org_catalog.json"
QUERIES_FILE = "agent_repo_queries.yaml"
TOP = 5
QUERY_PROMPT = (
    'In the {org} GitHub org, a developer is looking for the repo they describe as: "{query}". '
    "Write the GitHub repository search query you would type to find it: 1 to 3 words, no "
    "qualifiers. Only the query, nothing else."
)
# github-search-masked: the agent writes its search for an org it knows nothing of (the org's
# name masked), as for a private org; GitHub's search then runs in the real org.
LOCATORS = ("cairn", "github-search", "github-search-masked")
MASK = "veltrix"


class RepoQuery(Frozen):
    id: str
    query: str
    answers: tuple[str, ...]  # repo names in the org: any one counts
    note: str = ""


class RepoSet(Frozen):
    host: str = "github.com"
    org: str
    split: Literal["dev", "held"]
    queries: tuple[RepoQuery, ...]


class AgentQueries(Frozen):
    model: str
    generated: str = ""
    prompt: str = ""
    queries: dict[str, dict[str, str]]  # locator -> phrase id -> what the agent typed


@dataclass(frozen=True)
class RepoOutcome:
    query: str
    split: str
    locator: str
    found: tuple[str, ...]
    rank: int | None
    ms: float


def load_repo_set(suite_dir: Path) -> RepoSet:
    path = suite_dir / REPOS_FILE
    try:
        return RepoSet.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise CairnError(f"invalid repos key {path}: {exc}") from exc


def write_catalog(suite_dir: Path, client: GitHub, rset: RepoSet) -> OrgCatalog:
    catalog = build_catalog(client, rset.org, rset.host)
    save_catalog(suite_dir / CATALOG_FILE, catalog)
    return catalog


def read_catalog(suite_dir: Path) -> OrgCatalog:
    catalog = load_catalog(suite_dir / CATALOG_FILE)
    if catalog is None:
        raise CairnError(f"no {suite_dir / CATALOG_FILE}: make it first with --make-catalog")
    return catalog


def load_queries(suite_dir: Path) -> dict[str, dict[str, str]]:
    path = suite_dir / QUERIES_FILE
    if not path.is_file():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return AgentQueries.model_validate(raw).queries
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise CairnError(f"invalid agent queries {path}: {exc}") from exc


def ask_model(prompt: str, model: str = TERMS_MODEL) -> str:
    from cairn.bench.runner import ClaudeRunner  # the benchmark's isolated runner

    with tempfile.TemporaryDirectory(prefix="cairn-repo-query-") as tmp:
        result = ClaudeRunner(model=model, timeout=120).run(prompt, Path(tmp), Path(tmp), None)
    if result.is_error:
        raise CairnError(f"claude couldn't answer: {result.result_text.strip()[:200]}")
    return parse_query(result.result_text)


def parse_query(text: str) -> str:
    """The first line that reads as a query: quotes, backticks and qualifiers dropped."""
    for raw in text.splitlines():
        line = raw.strip().strip("`'\"").strip()
        kept = [w for w in line.split() if ":" not in w]
        if kept and not line.endswith(":"):
            return " ".join(kept)[:100]
    return ""


def query_prompt(rset: RepoSet, query: RepoQuery, *, masked: bool) -> str:
    text = QUERY_PROMPT.replace("{org}", rset.org).replace("{query}", query.query)
    return _masked(text, rset.org, MASK) if masked else text


def _masked(text: str, name: str, mask: str) -> str:
    return re.sub(re.escape(name), mask, text, flags=re.IGNORECASE)


def write_queries(
    suite_dir: Path,
    rset: RepoSet,
    ask: Callable[[str], str] | None = None,
    *,
    model: str = TERMS_MODEL,
    today: str = "",
) -> dict[str, dict[str, str]]:
    asker = ask or (lambda prompt: ask_model(prompt, model))
    queries = load_queries(suite_dir)
    for locator in ("github-search", "github-search-masked"):
        mine = queries.setdefault(locator, {})
        for q in rset.queries:
            if not mine.get(q.id):
                mine[q.id] = asker(query_prompt(rset, q, masked=locator.endswith("-masked")))
    ordered = {
        locator: {q.id: by_id[q.id] for q in rset.queries if q.id in by_id}
        for locator, by_id in queries.items()
    }
    doc = AgentQueries(model=model, generated=today, prompt=QUERY_PROMPT, queries=ordered)
    header = (
        "# The GitHub repository search an agent would type for each phrase in repos.yaml:\n"
        "# written by a model (cairn bench-repos --make-queries), never edited by hand.\n"
    )
    body = yaml.safe_dump(doc.model_dump(), sort_keys=False, width=100, allow_unicode=True)
    (suite_dir / QUERIES_FILE).write_text(header + body, encoding="utf-8", newline="\n")
    return ordered


def github_search(client: GitHub, org: str, words: str) -> tuple[tuple[str, ...], float]:
    """GitHub's repository search within the org: repo names, best first, and the request's ms."""
    if not words.strip():
        return (), 0.0
    names, ms = client.search_repos(f"{words} org:{org}", per_page=TOP)
    owned = tuple(n.partition("/")[2] for n in names if n.partition("/")[0].lower() == org.lower())
    return owned, ms


def evaluate(
    rset: RepoSet,
    catalog: OrgCatalog,
    agent_queries: Mapping[str, Mapping[str, str]],
    *,
    client: GitHub | None = None,
    locators: Iterable[str] = LOCATORS,
) -> list[RepoOutcome]:
    outcomes = []
    index = CatalogIndex.of(catalog)
    for q in rset.queries:
        answers = {a.lower() for a in q.answers}
        for locator in locators:
            if locator == "cairn":
                started = time.perf_counter()
                found = tuple(m.repo.name.partition("/")[2] for m in find_repos(index, q.query))
                ms = (time.perf_counter() - started) * 1000
            else:
                if client is None:
                    raise CairnError("github-search needs a GitHub client")
                typed = agent_queries.get(locator, {}).get(q.id, "")
                if locator.endswith("-masked"):
                    typed = _masked(typed, MASK, rset.org)
                found, ms = github_search(client, rset.org, typed)
            rank = next((i + 1 for i, f in enumerate(found) if f.lower() in answers), None)
            outcomes.append(RepoOutcome(q.id, rset.split, locator, found[:TOP], rank, round(ms, 2)))
    return outcomes


def report(outcomes: Iterable[RepoOutcome]) -> str:
    rows = list(outcomes)
    lines = [
        "| split | locator | n | hit@1 | hit@5 | MRR@5 | median ms |",
        "|---|---|---|---|---|---|---|",
    ]
    for split in sorted({o.split for o in rows}, key=["dev", "held"].index):
        for locator in dict.fromkeys(o.locator for o in rows):
            group = [o for o in rows if o.split == split and o.locator == locator]
            if not group:
                continue
            n = len(group)
            ms = sorted(o.ms for o in group)[n // 2]
            lines.append(
                f"| {split} | {locator} | {n} | {sum(o.rank == 1 for o in group) / n:.2f} | "
                f"{sum(o.rank is not None for o in group) / n:.2f} | "
                f"{sum(1 / o.rank for o in group if o.rank) / n:.2f} | {ms:.1f} |"
            )
    return "\n".join(lines) + "\n"


def outcomes_json(outcomes: Iterable[RepoOutcome]) -> str:
    return json.dumps([o.__dict__ for o in outcomes], indent=1)
