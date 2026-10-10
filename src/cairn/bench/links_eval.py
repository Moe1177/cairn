"""The offline link benchmark: how many of a workspace's real links cairn finds, and how many it
finds that aren't real, on real repos (no agent and no cost).

Each suite's `links.yaml` lists the pairs of repos that really link, written from the code and
never from cairn's output. A link is scored as a pair of repos, whatever edge type cairn gives it:
asked "what does this repo link to?", a user needs the right repos, not the right label. Links
cairn shows by default (extracted and inferred) are scored apart from its unconfirmed
suggestions, which `cairn links --all` adds.
"""

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, ValidationError, model_validator

from cairn.errors import CairnError
from cairn.model.graph import SYMMETRIC_TYPES, Confidence, Edge, EdgeType, Frozen
from cairn.scan import scan_workspace

LINKS_FILE = "links.yaml"
KINDS = ("http", "grpc", "pubsub", "package", "database", "deploys", "resource", "path", "docs")
Pair = frozenset[str]
_UNDIRECTED = SYMMETRIC_TYPES | {EdgeType.MENTIONS}


class TrueLink(Frozen):
    source: str = Field(alias="from")
    target: str = Field(alias="to")
    kind: Literal[
        "http", "grpc", "pubsub", "package", "database", "deploys", "resource", "path", "docs"
    ]
    note: str = ""

    @model_validator(mode="after")
    def _two_repos(self) -> "TrueLink":
        if self.source == self.target:
            raise ValueError(f"a link joins two repos, not {self.source} to itself")
        return self

    @property
    def pair(self) -> Pair:
        return frozenset((self.source, self.target))


class Unsure(Frozen):
    """A pair the key won't call right or wrong (a link that depends on how it's deployed)."""

    between: tuple[str, str]
    note: str = ""


class LinkSet(Frozen):
    split: Literal["dev", "held"]
    links: tuple[TrueLink, ...]
    unsure: tuple[Unsure, ...] = ()


@dataclass(frozen=True)
class SuiteScore:
    suite: str
    split: str
    view: Literal["shown", "all"]
    truth: int
    predicted: int  # pairs cairn links, leaving out the unsure ones
    hits: int
    directed_hits: int  # hits whose direction cairn gets right (or that have none)
    false_positives: tuple[str, ...]  # "a ~ b (calls_http inferred)"
    false_negatives: tuple[str, ...]  # "a -> b (http)"
    wrong_direction: tuple[str, ...]  # "a -> b (http), cairn: b -> a (calls_http)"
    recall_by_kind: tuple[tuple[str, int, int], ...]  # (kind, found, total)

    @property
    def precision(self) -> float:
        return self.hits / self.predicted if self.predicted else 1.0

    @property
    def recall(self) -> float:
        return self.hits / self.truth if self.truth else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0

    @property
    def direction(self) -> float:
        return self.directed_hits / self.hits if self.hits else 1.0


def load_link_set(suite_dir: Path) -> LinkSet:
    path = suite_dir / LINKS_FILE
    try:
        return LinkSet.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise CairnError(f"invalid link key {path}: {exc}") from exc


def key_problems(repo_ids: Iterable[str], link_set: LinkSet) -> list[str]:
    """Repos the key names that the scan didn't find: checked before anything is scored."""
    known = set(repo_ids)
    named = [r for link in link_set.links for r in (link.source, link.target)]
    named += [r for unsure in link_set.unsure for r in unsure.between]
    problems = [f"no repo {r}" for r in dict.fromkeys(named) if r not in known]
    pairs = [link.pair for link in link_set.links]
    problems += [f"listed twice: {' ~ '.join(sorted(p))}" for p in _repeats(pairs)]
    return problems


def evaluate(ws: Path, suite: str, link_set: LinkSet) -> tuple[SuiteScore, SuiteScore]:
    """Scan the workspace and score it against the key: links shown by default, then all."""
    workspace = scan_workspace(ws).workspace
    problems = key_problems((r.id for r in workspace.repos), link_set)
    if problems:
        raise CairnError(f"the link key of {suite} doesn't match its repos: {'; '.join(problems)}")
    shown = [e for e in workspace.edges if e.confidence is not Confidence.AMBIGUOUS]
    return (
        score(suite, link_set, shown, view="shown"),
        score(suite, link_set, workspace.edges, view="all"),
    )


def score(
    suite: str, link_set: LinkSet, edges: Sequence[Edge], *, view: Literal["shown", "all"]
) -> SuiteScore:
    by_pair: dict[Pair, list[Edge]] = {}
    for edge in edges:
        by_pair.setdefault(frozenset((edge.source, edge.target)), []).append(edge)
    unsure = {frozenset(u.between) for u in link_set.unsure}
    truth = {link.pair: link for link in link_set.links}
    predicted = {pair for pair in by_pair if pair not in unsure}
    hits = predicted & set(truth)
    backwards = sorted((p for p in hits if not _directed(truth[p], by_pair[p])), key=sorted)
    kinds = []
    for kind in KINDS:
        total = [link for link in link_set.links if link.kind == kind]
        if total:
            kinds.append((kind, sum(1 for link in total if link.pair in hits), len(total)))
    return SuiteScore(
        suite=suite,
        split=link_set.split,
        view=view,
        truth=len(truth),
        predicted=len(predicted),
        hits=len(hits),
        directed_hits=len(hits) - len(backwards),
        false_positives=tuple(sorted(_describe_edges(by_pair[p]) for p in predicted - hits)),
        false_negatives=tuple(
            sorted(
                f"{link.source} -> {link.target} ({link.kind})"
                for link in link_set.links
                if link.pair not in hits
            )
        ),
        wrong_direction=tuple(_backwards(truth[p], by_pair[p]) for p in backwards),
        recall_by_kind=tuple(kinds),
    )


def summarize(scores: Sequence[SuiteScore]) -> str:
    lines = [
        "| split | suite | links | n | cairn | precision | recall | F1 | direction |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for view in ("shown", "all"):
        group = [s for s in scores if s.view == view]
        lines += [_row(s.split, s.suite, view, [s]) for s in group]
        if len(group) > 1:
            for split in ("dev", "held"):
                part = [s for s in group if s.split == split]
                if len(part) > 1:
                    lines.append(_row(split, "**all**", view, part))
    for s in (s for s in scores if s.view == "shown"):
        lines += ["", f"### {s.suite}", ""]
        kinds = ", ".join(f"{k} {found}/{total}" for k, found, total in s.recall_by_kind)
        lines.append(f"Found by kind: {kinds}")
        lines += _listing("Missed", s.false_negatives)
        lines += _listing("Found the wrong way round", s.wrong_direction)
        lines += _listing("Not real links (shown)", s.false_positives)
        extra = next((a for a in scores if a.view == "all" and a.suite == s.suite), None)
        if extra is not None:
            unconfirmed = sorted(set(extra.false_positives) - set(s.false_positives))
            lines += _listing("Not real links (unconfirmed suggestions)", tuple(unconfirmed))
    return "\n".join(lines) + "\n"


def scores_json(scores: Iterable[SuiteScore]) -> str:
    rows = []
    for s in scores:
        row = dict(s.__dict__)
        row.update(precision=s.precision, recall=s.recall, f1=s.f1, direction=s.direction)
        rows.append(row)
    return json.dumps(rows, indent=1)


def _row(split: str, suite: str, view: str, group: list[SuiteScore]) -> str:
    truth = sum(s.truth for s in group)
    predicted = sum(s.predicted for s in group)
    hits = sum(s.hits for s in group)
    directed = sum(s.directed_hits for s in group)
    precision = hits / predicted if predicted else 1.0
    recall = hits / truth if truth else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    direction = directed / hits if hits else 1.0
    return (
        f"| {split} | {suite} | {view} | {truth} | {predicted} | {precision:.2f} | {recall:.2f} | "
        f"{f1:.2f} | {direction:.2f} |"
    )


def _directed(link: TrueLink, edges: list[Edge]) -> bool:
    """Right when one of cairn's edges for the pair points the same way, or has no direction. A
    README naming another repo says the two relate, not which one uses the other."""
    return any(
        e.type in _UNDIRECTED or (e.source, e.target) == (link.source, link.target) for e in edges
    )


def _backwards(link: TrueLink, edges: list[Edge]) -> str:
    found = ", ".join(sorted({f"{e.source} -> {e.target} ({e.type.value})" for e in edges}))
    return f"{link.source} -> {link.target} ({link.kind}); cairn: {found}"


def _describe_edges(edges: list[Edge]) -> str:
    a, b = sorted({edges[0].source, edges[0].target})
    types = ", ".join(sorted({f"{e.type.value} {e.confidence.value}" for e in edges}))
    return f"{a} ~ {b} ({types})"


def _listing(title: str, items: tuple[str, ...] | list[str]) -> list[str]:
    if not items:
        return [f"{title}: none"]
    return [f"{title}:", *(f"- {item}" for item in items)]


def _repeats(pairs: list[Pair]) -> list[Pair]:
    seen: set[Pair] = set()
    repeated = []
    for pair in pairs:
        if pair in seen and pair not in repeated:
            repeated.append(pair)
        seen.add(pair)
    return repeated
