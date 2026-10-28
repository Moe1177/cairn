"""The org's repos, as a catalog an agent can search: "the terraform provider for AWS" ->
hashicorp/terraform-provider-aws, for repos nobody cloned.

Read from the org's repo listing (one request per 100 repos: hashicorp's 604 in about 2.5 s),
then cached for a day. A phrase is matched against each repo's name, description and topics,
rarer words counting more, in about a millisecond: GitHub's own repo search needs every word of
a query to match, so a phrase an agent writes rarely finds anything there.
"""

import math
import re
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from cairn.errors import CairnError
from cairn.model.graph import Frozen
from cairn.org.profile import active_repos, older_than, save_cache
from cairn.remote.host import CodeHost
from cairn.security.text import clean_inline

MAX_AGE = timedelta(days=1)
MAX_REPOS = 10_000
_DESCRIPTION = 160
_TOPICS = 10
_NAME_WEIGHT = 2.0  # a word in the repo's name says more than one in its description
_TOKEN = re.compile(r"[a-z0-9]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_SUFFIX = re.compile(r"(?:ing|ed|s)$")  # "services" -> service, as "service" is
_SYNONYMS = {"k8s": "kubernetes", "golang": "go", "js": "javascript", "ts": "typescript"}
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "any",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "into",
        "is",
        "it",
        "its",
        "my",
        "of",
        "on",
        "or",
        "our",
        "that",
        "the",
        "their",
        "this",
        "to",
        "tool",
        "tools",
        "we",
        "which",
        "with",
        "without",
        "repo",
        "repository",
        "project",
        "code",
        "one",
    ]
)


class CatalogRepo(Frozen):
    name: str  # owner/name
    description: str = ""
    language: str = ""
    topics: tuple[str, ...] = ()
    pushed: str = ""
    fork: bool = False


class OrgCatalog(Frozen):
    org: str
    host: str
    built: str  # ISO time, UTC
    ms: float
    repos: tuple[CatalogRepo, ...] = ()  # active ones, most recently pushed first


@dataclass(frozen=True)
class RepoMatch:
    repo: CatalogRepo
    score: float


def build_catalog(
    client: CodeHost,
    org: str,
    host: str = "github.com",
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> OrgCatalog:
    started = time.perf_counter()
    listed = active_repos(client, org, MAX_REPOS, max_pages=MAX_REPOS // 100)
    if not listed:
        raise CairnError(f"{org} has no repos cairn can read (or none that aren't archived)")
    repos = tuple(
        CatalogRepo(
            name=repo.name,
            description=clean_inline(repo.description, _DESCRIPTION),
            language=clean_inline(repo.language, 40),
            topics=tuple(clean_inline(t, 50) for t in repo.topics[:_TOPICS]),
            pushed=repo.pushed,
            fork=repo.fork,
        )
        for repo in listed
    )
    return OrgCatalog(
        org=org,
        host=host,
        built=now().isoformat(timespec="seconds"),
        ms=round((time.perf_counter() - started) * 1000, 1),
        repos=repos,
    )


def words(text: str, *, joined: bool = False) -> list[str]:
    """Search words: camelCase and separators split, lower case, plural and -ing/-ed endings
    dropped (so "renders" and "rendering" meet), common words left out. With `joined`, each
    pair of neighbours also as one word, for names written as one ("data plane": dataplane)."""
    raw: list[str] = [_SYNONYMS.get(w) or w for w in _TOKEN.findall(_CAMEL.sub(" ", text).lower())]
    pairs = [a + b for a, b in zip(raw, raw[1:], strict=False)] if joined else []
    return [_stem(w) for w in (*raw, *pairs) if w not in _STOPWORDS]


def _stem(word: str) -> str:
    return _SUFFIX.sub("", word) if len(word) > 4 and not word.endswith("ss") else word


@dataclass(frozen=True)
class CatalogIndex:
    """A catalog's words, counted once: a search then costs one pass over the repos."""

    catalog: OrgCatalog
    docs: tuple[tuple[CatalogRepo, frozenset[str], frozenset[str]], ...]
    seen: Mapping[str, int]  # word -> repos it appears in

    @classmethod
    def of(cls, catalog: OrgCatalog) -> "CatalogIndex":
        docs = tuple(
            (r, frozenset(words(_short(r.name))), frozenset(words(_about(r))))
            for r in catalog.repos
        )
        return cls(catalog, docs, Counter(w for _, name, about in docs for w in name | about))


def find_repos(index: CatalogIndex, query: str, *, limit: int = 5) -> list[RepoMatch]:
    """The repos a phrase most likely means. A repo's exact name (or owner/name) comes first;
    otherwise each query word found counts by how rare it is in the org, double in the name."""
    exact = find_repo(index.catalog, query)
    if exact is not None:
        return [RepoMatch(exact, 1.0)]
    asked = set(words(query, joined=True))
    if not asked:
        return []
    total = len(index.docs)
    scored = []
    for repo, name, about in index.docs:
        score = sum(
            math.log(1 + total / index.seen[word]) * (_NAME_WEIGHT if word in name else 1.0)
            for word in asked
            if word in name or word in about
        )
        if score > 0:
            scored.append(RepoMatch(repo, score))
    scored.sort(key=lambda m: (-m.score, m.repo.fork, m.repo.name.lower()))
    return scored[:limit]


def _about(repo: CatalogRepo) -> str:
    return f"{repo.description} {' '.join(repo.topics)}"


def _short(name: str) -> str:
    """A repo's path inside its org (on GitLab, with any subgroups)."""
    return name.partition("/")[2] or name


def find_repo(catalog: OrgCatalog, name: str) -> CatalogRepo | None:
    """A repo of the catalog by its full path, its path inside the org, or (when only one
    repo's path ends with it, as in a GitLab group's subgroups) the end of its path. Any
    case."""
    wanted = name.strip().strip("/").lower()
    inside = f"{catalog.org.lower()}/{wanted}"
    exact = [r for r in catalog.repos if r.name.lower() in (wanted, inside)]
    if exact:
        return exact[0]
    ends = [r for r in catalog.repos if r.name.lower().endswith(f"/{wanted}")]
    return ends[0] if len(ends) == 1 else None


def render_matches(catalog: OrgCatalog, matches: Sequence[RepoMatch]) -> list[str]:
    return [
        f"- {m.repo.name} (org {catalog.org}, not cloned)"
        + (f": {m.repo.description}" if m.repo.description else "")
        + (f" · {m.repo.language}" if m.repo.language else "")
        + f" → repo_card {m.repo.name}"
        for m in matches
    ]


def render_org_card(
    repo: CatalogRepo, extra: Iterable[str] = (), *, searchable: bool = True
) -> str:
    """What cairn knows of an org repo nobody cloned: the listing's facts, and (from the
    packages index, when read) what it defines and who uses it. `searchable`: whether its host
    has code search for find_similar (plain git hasn't)."""
    lines = [
        f"# {repo.name} (org repo, not cloned)",
        "",
        repo.description or "No description.",
        "",
    ]
    facts = [f"Language: {repo.language}"] if repo.language else []
    if repo.topics:
        facts.append(f"Topics: {', '.join(repo.topics)}")
    if _DATE.match(repo.pushed):  # plain git's is a commit id, not a time
        facts.append(f"Last push: {repo.pushed[:10]}")
    if repo.fork:
        facts.append("A fork.")
    lines += [f"- {fact}" for fact in facts]
    lines += list(extra)
    then = (
        "; search_org and find_similar search its code with the rest of the org."
        if searchable
        else "."
    )
    lines += [
        "",
        f"Read its files with read_org_file (repo {repo.name}, path README.md first){then}",
    ]
    return "\n".join(lines)


def needs_build(catalog: OrgCatalog, now: datetime) -> bool:
    return older_than(catalog.built, now, MAX_AGE)


def load_catalog(path: Path) -> OrgCatalog | None:
    try:
        return OrgCatalog.model_validate_json(path.read_bytes())
    except (OSError, ValueError, ValidationError):
        return None


def save_catalog(path: Path, catalog: OrgCatalog) -> None:
    save_cache(path, catalog.model_dump_json())
