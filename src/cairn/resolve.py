"""Resolve a human phrase ("the admin dashboard") to workspace repos."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from difflib import SequenceMatcher

from cairn.model.graph import Repo, Workspace
from cairn.model.overrides import Authored
from cairn.render.index import one_liner

STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "my",
        "our",
        "repo",
        "repository",
        "project",
        "thing",
        "stuff",
        "service",
        "app",
        "code",
        "codebase",
        "one",
        "that",
        "this",
        "for",
        "of",
        "in",
        "to",
        "with",
    }
)
_SYNONYMS = {
    "golang": "go",
    "next": "nextjs",
    "ts": "typescript",
    "js": "javascript",
    "py": "python",
}
_TOKEN = re.compile(r"[a-z0-9@]+")
_FUZZY_MIN = 0.75
_NON_EXACT_CAP = 0.99


@dataclass(frozen=True)
class Match:
    repo_id: str
    score: float
    path: str
    one_liner: str


def resolve_repo(
    workspace: Workspace, authored: Mapping[str, Authored], query: str, *, limit: int = 5
) -> tuple[Match, ...]:
    raw = " ".join(query.lower().split())
    words = [t for t in _tokens(raw) if t not in STOPWORDS]
    if not words:
        return ()
    scored = []
    for repo in workspace.repos:
        notes = authored.get(repo.id)
        score = _score(raw, words, repo, notes)
        if score > 0:
            scored.append(
                Match(repo.id, round(min(score, 1.0), 4), repo.path, one_liner(repo, notes))
            )
    scored.sort(key=lambda m: (-m.score, m.repo_id))
    return tuple(scored[:limit])


def _stem(token: str) -> str:
    return (
        token[:-1] if len(token) > 3 and token.endswith("s") and not token.endswith("ss") else token
    )


def _tokens(text: str) -> list[str]:
    return [_stem(_SYNONYMS.get(t) or t) for t in _TOKEN.findall(text.lower())]


def _score(raw: str, words: list[str], repo: Repo, authored: Authored | None) -> float:
    names = [n.lower() for n in (repo.id, *repo.aliases, *(authored.aliases if authored else ()))]
    if raw in names or "-".join(words) in names or " ".join(words) in names:
        return 1.0
    query = set(words)
    name_tokens = {t for n in names for t in _tokens(n)}
    summary = (
        (authored.summary if authored and authored.summary else None) or repo.readme_excerpt or ""
    )
    name_overlap = len(query & name_tokens) / len(query)
    summary_overlap = len(query & set(_tokens(summary))) / len(query)
    stack_hit = 1.0 if query & {_stem(s) for s in repo.stack} else 0.0
    fuzzy = max((SequenceMatcher(None, "-".join(words), n).ratio() for n in names), default=0.0)
    fuzzy = fuzzy if fuzzy >= _FUZZY_MIN else 0.0
    partial = max(0.8 * name_overlap, 0.9 * fuzzy) + 0.3 * summary_overlap + 0.25 * stack_hit
    return min(partial, _NON_EXACT_CAP)
