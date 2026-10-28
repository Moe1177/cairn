"""find_similar: the org's existing implementations of a feature, without cloning anything.

Code search matches words, and the words of a request ("stop one client flooding our API")
are rarely the code's (`RateLimiter`, `X-RateLimit-Remaining`). So the caller, an agent that
knows the request, passes a few terms the code would use; each becomes one code search, all
run at once. Hits are merged by reciprocal rank (a file several searches find rises), and
what isn't prior art is weighed down or dropped: vendored copies of libraries, docs and
notebooks, tests, generated files.
"""

import re
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from cairn.errors import CairnError
from cairn.locate.terms import concept_terms, literal_terms
from cairn.remote.host import CodeHit, CodeHost, SearchPage
from cairn.security.redact import redact
from cairn.security.text import clean_inline

MAX_TERMS = 4  # each is a search, and code search allows 10 a minute
PER_SEARCH = 30
_RRF_K = 10
_TERM_MAX = 100
_FRAGMENT_MAX = 240
_PATH_MAX = 300  # a path is one line however long a repo makes it

# Copies of someone else's code: never the org's prior art, however well they match.
_VENDORED = re.compile(
    r"(?:^|/)(?:node_modules|site-packages|dist-packages|\.venv|venv|vendor|third_party|"
    r"bower_components|\.yarn|cdk\.out|\.aws-sam|\.serverless|\.terraform|__pycache__|"
    r"botocore|boto3|urllib3|layers?/python|lambda_package|"
    r"asset\.[0-9a-f]{8,})(?:/|$)",
    re.IGNORECASE,
)
_GENERATED = re.compile(r"\.min\.(?:js|css)$|(?:^|/)(?:package-lock\.json|yarn\.lock|.*\.lock)$")
_DOCS = re.compile(r"\.(?:md|mdx|rst|txt|adoc|html?|ipynb)$", re.IGNORECASE)
_DATA = re.compile(r"\.(?:json|ya?ml|toml|csv|xml|ini|cfg|properties)$", re.IGNORECASE)
_TESTS = re.compile(
    r"(?:^|/)(?:tests?|__tests__|spec|e2e)/|\.(?:test|spec)\.[cm]?[jt]sx?$|_test\.(?:py|go)$"
    r"|(?:^|/)test_[^/]*\.py$",
    re.IGNORECASE,
)
# Qualifiers that would move a search out of the org; the useful ones (path:, language:,
# filename:, extension:) are kept. Hits from outside the org are dropped anyway (_rank).
_ESCAPES = re.compile(r"(?i)(?<![\w-])-?(?:org|repo|user|owner|is|fork|archived):[^\s)]*")
# Long-lived threads: each keeps its keep-alive connection, so a session's later searches
# skip the TLS handshake.
_POOL = ThreadPoolExecutor(max_workers=MAX_TERMS, thread_name_prefix="cairn-search")


@dataclass(frozen=True)
class Similar:
    repo: str  # owner/name
    path: str
    score: float
    matched: tuple[str, ...]  # the terms whose search found it
    fragments: tuple[str, ...] = ()


@dataclass(frozen=True)
class SimilarResult:
    org: str
    terms: tuple[str, ...]
    hits: tuple[Similar, ...]
    ms: float  # wall time of the searches (they run at once)
    waited: float  # seconds of that spent waiting out rate limits
    searches: int
    failed: tuple[str, ...] = ()  # "term: why" for each search that didn't answer


def weight(path: str) -> float:
    """How much a match in `path` counts as prior art (0: not at all)."""
    if _VENDORED.search(path) or _GENERATED.search(path):
        return 0.0
    if _TESTS.search(path):
        return 0.4
    if _DATA.search(path):
        return 0.3
    if _DOCS.search(path):
        return 0.25
    return 1.0


def clean_terms(terms: Sequence[str], task: str) -> tuple[str, ...]:
    """The searches to run: the caller's terms (kept inside the org), else words of the task."""
    cleaned = []
    for term in terms:
        text = " ".join(_ESCAPES.sub(" ", term).split())[:_TERM_MAX]
        if text and text.lower() not in {c.lower() for c in cleaned}:
            cleaned.append(text)
    if not cleaned:  # no terms: the task's own words, code identifiers first
        words = list(dict.fromkeys((*literal_terms(task), *concept_terms(task))))
        cleaned = [" ".join(words[:3])] if words else []
    return tuple(cleaned[:MAX_TERMS])


def find_similar(
    client: CodeHost,
    org: str,
    task: str,
    terms: Sequence[str] = (),
    *,
    limit: int = 10,
    per_search: int = PER_SEARCH,
) -> SimilarResult:
    queries = clean_terms(terms, task)
    started = time.perf_counter()

    def search(query: str) -> SearchPage | CairnError:
        try:
            return client.search_code(f"{query} org:{org}", per_page=per_search)
        except CairnError as exc:  # one search failing still leaves the others' hits
            return exc

    answers = list(_POOL.map(search, queries))
    ms = (time.perf_counter() - started) * 1000
    pages: list[tuple[str, SearchPage]] = []
    errors: list[tuple[str, CairnError]] = []
    for query, answer in zip(queries, answers, strict=True):
        if isinstance(answer, CairnError):
            errors.append((query, answer))
        else:
            pages.append((query, answer))
    if queries and not pages:
        raise errors[0][1]
    hits = _rank(org, pages)[:limit]
    waited = max((page.waited for _, page in pages), default=0.0)  # they waited side by side
    failed = tuple(f"{q}: {exc}" for q, exc in errors)
    return SimilarResult(org, queries, tuple(hits), ms, waited, len(queries), failed)


def _rank(org: str, pages: Sequence[tuple[str, SearchPage]]) -> list[Similar]:
    """Hits merged by reciprocal rank, the org's own only: whatever a term asked for, a
    search can't hand back another owner's code."""
    owner = f"{org.lower()}/"
    scores: dict[tuple[str, str], float] = {}
    matched: dict[tuple[str, str], list[str]] = {}
    found: dict[tuple[str, str], CodeHit] = {}
    for query, page in pages:
        for rank, hit in enumerate(page.hits, start=1):
            w = weight(hit.path)
            if w == 0.0 or not hit.repo.lower().startswith(owner):
                continue
            key = (hit.repo.lower(), hit.path)
            scores[key] = scores.get(key, 0.0) + w / (_RRF_K + rank)
            matched.setdefault(key, []).append(query)
            found.setdefault(key, hit)
    ordered = sorted(scores, key=lambda k: (-scores[k], k))
    return [
        Similar(
            repo=found[key].repo,
            path=found[key].path,
            score=round(scores[key], 4),
            matched=tuple(matched[key]),
            fragments=tuple(_fragment(f) for f in found[key].fragments[:2]),
        )
        for key in ordered
    ]


def _fragment(text: str) -> str:
    # Like a card's snippets: a key or token in matched code is masked before an agent sees it.
    return redact(" ".join(text.split()))[:_FRAGMENT_MAX]


def render_similar(result: SimilarResult, *, uses: bool = False) -> str:
    """The answer as an agent reads it: best first, each with why it matched. `uses`: the hits
    are where the org's code uses the terms (search_org), not prior art to copy."""
    searched = ", ".join(f"`{t}`" for t in result.terms) or "nothing (no terms)"
    title = f"Uses in {result.org} of" if uses else f"Prior art in {result.org} for"
    head = (
        f"{title} {searched}: {len(result.hits)} files "
        f"({result.searches} searches, {result.ms / 1000:.1f}s"
        + (
            f", {result.waited:.0f}s of it waiting for the host's rate limit"
            if result.waited
            else ""
        )
        + ")."
    )
    notes = [f"(a search failed: {why})" for why in result.failed]
    if not result.hits:
        return "\n".join(
            [
                head,
                *notes,
                "Nothing found. Try terms the code itself would contain: "
                + (
                    "the exact export, metric, env var, image, queue or function name."
                    if uses
                    else "class or function names, SDK calls, library names, config keys."
                ),
            ]
        )
    lines = [head, *notes]
    for hit in result.hits:
        name = hit.repo[len(result.org) + 1 :]  # always the org's: _rank keeps no other
        # A path and its code are the repo's authors' text: each stays one inert line.
        where = clean_inline(f"{name}/{hit.path}", _PATH_MAX)
        lines.append(f"- {where}  (matched {', '.join(hit.matched)})")
        lines.extend(
            f"    {clean_inline(fragment, _FRAGMENT_MAX)}" for fragment in hit.fragments[:1]
        )
    lines.append(
        "Read a match with read_org_file(repo, path) to confirm it; the host's code search "
        "covers default branches and may miss a file, so a short list isn't proof of no others."
        if uses
        else "Read a file with read_org_file(repo, path) before copying its approach; "
        "several matches in one repo usually mean that repo owns the pattern."
    )
    return "\n".join(lines)
