"""The offline locate benchmark (plan B2): which locator finds the answer file, by question kind.

No agent and no cost: each suite's `locate.yaml` lists questions with the files that answer them
(written from the code, never from a locator's output); every locator answers every question and
is scored on where the first answer file lands, how much text it returns, and how long it takes.
"""

import hashlib
import json
import shutil
import statistics
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import ValidationError, field_validator

from cairn.bench.sources import fetch_sources, remotes
from cairn.bench.suite import load_suite
from cairn.bench.workspace import materialize
from cairn.errors import CairnError
from cairn.locate.hybrid import run_locator
from cairn.locate.workspace import fan_out, scoped_locate
from cairn.model.graph import Frozen
from cairn.providers.graph import Graph, load_graph
from cairn.providers.graphify import GraphifyProvider
from cairn.providers.meta import deep_dir
from cairn.scan import scan_workspace

LOCATE_FILE = "locate.yaml"
CATEGORIES = ("literal", "vocabulary", "chain", "broad", "cross-repo")
_COMPLETE = ".complete"


class LocateQuery(Frozen):
    id: str
    category: Literal["literal", "vocabulary", "chain", "broad", "cross-repo"]
    repo: str  # where the developer is working when they ask
    question: str
    answers: tuple[str, ...]  # workspace paths, repo/path: any one counts as found
    note: str = ""

    @field_validator("answers")
    @classmethod
    def _workspace_paths(cls, answers: tuple[str, ...]) -> tuple[str, ...]:
        if not answers or any("/" not in a or a.startswith("/") or ".." in a for a in answers):
            raise ValueError("answers must be one or more workspace paths: repo/path")
        return answers


class LocateSet(Frozen):
    split: Literal["dev", "held"]
    queries: tuple[LocateQuery, ...]


@dataclass(frozen=True)
class Outcome:
    query_id: str
    split: str
    category: str
    mode: str
    route: str
    rank: int | None  # 1-based position of the first answer file; None when not returned
    recall_at_5: float  # share of the answer files in the top five
    tokens: int  # size of the answer as an agent would read it (~4 characters a token)
    ms: float


def load_locate_set(suite_dir: Path) -> LocateSet:
    path = suite_dir / LOCATE_FILE
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return LocateSet.model_validate(data)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise CairnError(f"invalid locate key {path}: {exc}") from exc


def key_problems(ws: Path, locate_set: LocateSet) -> list[str]:
    """Answers that don't exist and repos that aren't in the workspace: a key must be checked
    against the code before any locator is scored on it."""
    problems = []
    for query in locate_set.queries:
        if not (ws / query.repo).is_dir():
            problems.append(f"{query.id}: no repo {query.repo}")
        problems.extend(
            f"{query.id}: no file {answer}"
            for answer in query.answers
            if not (ws / answer).is_file()
        )
    return problems


def prepare_locate_workspace(
    suite_dir: Path,
    cache_root: Path,
    *,
    provider: GraphifyProvider | None,
    timeout: float = 1800,
) -> tuple[Path, dict[str, Graph | None]]:
    """The suite's repos as git repos under `cache_root` (made once), with each repo's code
    graph: built with `provider` when missing, None when there is none."""
    suite = load_suite(suite_dir)
    source = fetch_sources(suite_dir, suite)
    ws = cache_root / f"{suite.name}-{_stamp(source, fetched=bool(suite.sources))}"
    if not (ws / _COMPLETE).is_file():
        if ws.exists():
            shutil.rmtree(ws)
        materialize(source, ws, remotes=remotes(suite), rename_dots=not suite.sources)
        (ws / _COMPLETE).write_text("", encoding="utf-8")
    graphs: dict[str, Graph | None] = {}
    for repo in sorted(p.name for p in ws.iterdir() if (p / ".git").exists()):
        path = deep_dir(ws, repo) / "graphify-out" / "graph.json"
        if not path.is_file() and provider is not None and provider.available():
            provider.build(ws, repo, ws / repo, timeout=timeout)
        graphs[repo] = load_graph(path) if path.is_file() else None
    return ws, graphs


def evaluate(
    ws: Path,
    graphs: dict[str, Graph | None],
    locate_set: LocateSet,
    modes: Sequence[str],
    *,
    limit: int = 10,
) -> list[Outcome]:
    """Every question searched the way `query` searches it (scoped_locate: the asked repo, repos
    it names, related repos unless a literal answered), whatever its category."""
    workspace = scan_workspace(ws).workspace
    outcomes = []
    for query in locate_set.queries:
        for mode in modes:

            def run(ids: list[str], mode: str = mode, question: str = query.question) -> dict:
                return {
                    repo: run_locator(mode, ws / repo, question, graphs.get(repo), limit=limit)
                    for repo in ids
                }

            started = time.perf_counter()
            results, _, _ = scoped_locate(workspace, query.repo, query.question, run)
            hits = fan_out(results, limit=limit)
            ms = (time.perf_counter() - started) * 1000
            paths = [f"{hit.repo}/{hit.file}" for hit in hits]
            rank = next((i + 1 for i, p in enumerate(paths) if p in query.answers), None)
            found = set(paths[:5]) & set(query.answers)
            text = "\n".join(
                f"- {p}:{hit.line or ''} {hit.why}" for p, hit in zip(paths, hits, strict=True)
            )
            routes = sorted({r.route for r in results.values() if r.hits}) or ["none"]
            outcomes.append(
                Outcome(
                    query_id=query.id,
                    split=locate_set.split,
                    category=query.category,
                    mode=mode,
                    route="+".join(routes) if len(routes) > 1 else routes[0],
                    rank=rank,
                    recall_at_5=len(found) / len(query.answers),
                    tokens=-(-len(text) // 4),
                    ms=round(ms, 2),
                )
            )
    return outcomes


def summarize(outcomes: Iterable[Outcome]) -> str:
    rows = list(outcomes)
    lines = [
        "| split | locator | category | n | hit@1 | hit@3 | hit@5 | MRR | recall@5 | tokens | ms |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    splits = sorted({o.split for o in rows}, key=["dev", "held"].index)
    modes = list(dict.fromkeys(o.mode for o in rows))
    for split in splits:
        for mode in modes:
            for category in (*CATEGORIES, "all"):
                group = [
                    o
                    for o in rows
                    if o.split == split
                    and o.mode == mode
                    and (category == "all" or o.category == category)
                ]
                if group:
                    lines.append(_row(split, mode, category, group))
    routes = [o for o in rows if o.mode == "hybrid"]
    if routes:
        lines += ["", "Hybrid routing (questions per locator that answered):", ""]
        lines += ["| split | category | routes |", "|---|---|---|"]
        for split in splits:
            for category in CATEGORIES:
                group = [o.route for o in routes if o.split == split and o.category == category]
                if group:
                    counts = ", ".join(
                        f"{r} {group.count(r)}" for r in sorted(set(group), key=group.index)
                    )
                    lines.append(f"| {split} | {category} | {counts} |")
    return "\n".join(lines) + "\n"


def _row(split: str, mode: str, category: str, group: list[Outcome]) -> str:
    n = len(group)

    def hit_at(k: int) -> float:
        return sum(1 for o in group if o.rank is not None and o.rank <= k) / n

    mrr = sum(1 / o.rank for o in group if o.rank is not None) / n
    recall = sum(o.recall_at_5 for o in group) / n
    tokens = sum(o.tokens for o in group) / n
    ms = statistics.median(o.ms for o in group)
    return (
        f"| {split} | {mode} | {category} | {n} | {hit_at(1):.2f} | {hit_at(3):.2f} | "
        f"{hit_at(5):.2f} | {mrr:.2f} | {recall:.2f} | {tokens:.0f} | {ms:.1f} |"
    )


def outcomes_json(outcomes: Iterable[Outcome]) -> str:
    return json.dumps([o.__dict__ for o in outcomes], indent=1)


def _stamp(source: Path, *, fetched: bool) -> str:
    if fetched:
        return source.name  # fetch_sources names the folder by its pinned commits
    digest = hashlib.sha1()
    for path in sorted(p for p in source.rglob("*") if p.is_file()):
        digest.update(path.relative_to(source).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]
