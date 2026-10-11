"""Can a task be answered by searching for its own words? (`cairn bench-reach`)

A task the agent can answer from one workspace-wide search for a term in its prompt says nothing
about a map: the search finds the answer as fast. This check runs every such search offline, the
way a careful agent would: each word, quoted string and route in the prompt, and each pair of
neighbouring words joined as code would join them (`queue worker` -> `queue-worker`,
`queue_worker`, `queueworker`), matched case-insensitively against every file's text and path.

A search "leads to" files when it matches few enough to read (at most `READABLE` files). A task
is reachable when the files its readable searches lead to, taken together, hold enough of the
answer to pass grading (PASS_RECALL). A prompt names a repo when one of its terms is part of that
repo's name and of at most `_NAMING` repos' names: an agent that lists the workspace goes there.

A task marked `hard` must be neither: no search for its words answers it, and it doesn't name a
repo the answer is in (other than the one the agent starts in). Its answer takes an identifier
found by reading code first, in a repo the agent has to work out.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from cairn.bench.grading import PASS_RECALL
from cairn.bench.suite import Task
from cairn.discover.files import DEFAULT_IGNORE_DIRS, iter_files, read_text

READABLE = 50  # files: about what an agent reads through from one search's file list
_NAMING = 2  # a term in more repo names than this doesn't single a repo out
_MIN_TERM = 3
# Vendored copies and generated output stay out (tasks say to ignore them); test fixtures don't.
_IGNORE = DEFAULT_IGNORE_DIRS - {"fixtures", "__fixtures__", "testdata"}
# A single quote opens and closes only beside a non-word: `the user's ... API's` is no quote.
_QUOTED = re.compile(r"\"([^\"\n]+)\"|(?<!\w)'([^'\n]+)'(?!\w)|`([^`\n]+)`")
_ROUTE = re.compile(r"(?<![\w/])/[\w./{}:-]*[\w}]")
_TOKEN = re.compile(r"[\w$][\w$./{}:-]*[\w$}]|[\w$]")
_TRIM = ".,;:"


@dataclass(frozen=True)
class Corpus:
    """Every searchable file of a workspace, lowercased: `repo/path` -> text."""

    texts: dict[str, str]
    repos: tuple[str, ...] = ()

    def search(self, term: str) -> frozenset[str]:
        needle = term.lower()
        return frozenset(f for f, text in self.texts.items() if needle in f or needle in text)


@dataclass(frozen=True)
class Reach:
    task_id: str
    hard: bool
    coverage: float  # share of the answer files the readable searches lead to
    best_term: str | None  # the search that leads to the most answer files
    best_hits: int
    best_files: int  # how many files that search matches
    checked: bool  # False: a keywords-only task, which has no answer files to reach
    named: tuple[str, ...] = ()  # answer repos (not the starting one) the prompt names
    missing: tuple[str, ...] = ()  # answer files that aren't in the workspace: a broken key

    @property
    def reachable(self) -> bool:
        return self.checked and self.coverage >= PASS_RECALL

    @property
    def problem(self) -> bool:
        """An answer file that doesn't exist, or a task marked hard that a search answers, that
        names where the answer is, or that has no answer files to check."""
        hard_but_easy = self.reachable or bool(self.named) or not self.checked
        return bool(self.missing) or (self.hard and hard_but_easy)


def load_corpus(ws: Path) -> Corpus:
    texts: dict[str, str] = {}
    repos = sorted(p for p in ws.iterdir() if p.is_dir() and (p / ".git").exists())
    for repo in repos:
        for path in iter_files(repo, ignore_dirs=_IGNORE):
            text = read_text(path)
            if text is not None:
                rel = f"{repo.name}/{path.relative_to(repo).as_posix()}"
                texts[rel.lower()] = text.lower()
    return Corpus(texts, tuple(r.name.lower() for r in repos))


def prompt_terms(prompt: str) -> list[str]:
    """What an agent could search for from the prompt alone."""
    terms: list[str] = []
    for match in _QUOTED.finditer(prompt):
        terms.append(next(g for g in match.groups() if g is not None))
    terms += _ROUTE.findall(prompt)
    words = [t.strip(_TRIM) for t in _TOKEN.findall(prompt)]
    words = [w for w in words if w]
    terms += words
    for left, right in zip(words, words[1:], strict=False):
        if left.isalnum() and right.isalnum() and min(len(left), len(right)) > 1:
            terms += [f"{left} {right}", f"{left}-{right}", f"{left}_{right}", f"{left}{right}"]
    # Parts of a compound (`repo/path`, `a.b.c`, `{name}` routes) are searches too.
    terms += [p for w in words for p in re.split(r"[/.{}:]+", w) if p and p != w]
    return list(dict.fromkeys(t for t in terms if len(t) >= _MIN_TERM))


def named_repos(
    terms: Iterable[str], answer_repos: Iterable[str], repos: tuple[str, ...]
) -> tuple[str, ...]:
    """The answer repos a term singles out by name (`queue worker` -> nats-queue-worker)."""
    named: set[str] = set()
    for term in terms:
        needle = term.lower()
        if len(needle) < 4 or needle.isdigit():
            continue
        holders = [r for r in repos if needle in r]
        if len(holders) <= _NAMING:
            named.update(r for r in holders if r in answer_repos)
    return tuple(sorted(named))


def reach(task: Task, corpus: Corpus, *, readable: int = READABLE) -> Reach:
    expected = frozenset(f.lower() for f in task.expect_files)
    if not expected:
        return Reach(task.id, task.hard, 0.0, None, 0, 0, checked=False)
    terms = prompt_terms(task.prompt)
    answer_repos = {f.split("/", 1)[0] for f in expected} - {task.repo.lower()}
    led_to: set[str] = set()
    best: tuple[int, int, str] | None = None  # (answer files hit, -files matched, term)
    for term in terms:
        found = corpus.search(term)
        if not found or len(found) > readable:
            continue
        hits = len(found & expected)
        led_to |= found & expected
        if hits and (best is None or (hits, -len(found)) > best[:2]):
            best = (hits, -len(found), term)
    return Reach(
        task_id=task.id,
        hard=task.hard,
        coverage=len(led_to) / len(expected),
        best_term=best[2] if best else None,
        best_hits=best[0] if best else 0,
        best_files=-best[1] if best else 0,
        checked=True,
        named=named_repos(terms, answer_repos, corpus.repos),
        missing=tuple(sorted(expected - corpus.texts.keys())),
    )


def summarize(suite: str, results: Iterable[Reach]) -> str:
    lines = [
        f"## {suite}",
        "",
        "| task | marked | answer files a search leads to | best search | repos named | verdict |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        marked = "hard" if r.hard else ""
        if not r.checked:
            lines.append(f"| {r.task_id} | {marked} | (keywords only) | | | not checked |")
            continue
        best = (
            f"`{r.best_term}` ({r.best_hits} of them, {r.best_files} files)" if r.best_term else ""
        )
        named = ", ".join(r.named)
        verdict = (
            "a search answers it"
            if r.reachable
            else "names where it is"
            if r.named
            else "needs a hop"
        )
        if r.missing:
            verdict = f"no such file: {', '.join(r.missing)}"
        elif r.problem:
            verdict += " (marked hard!)"
        lines.append(
            f"| {r.task_id} | {marked} | {r.coverage:.0%} | {best} | {named} | {verdict} |"
        )
    return "\n".join(lines) + "\n"
