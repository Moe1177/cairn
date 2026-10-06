"""Read a question for the code's own words (what grep can find) and for its intent."""

import re

MAX_TERMS = 8
_TERM_MAX = 120
_QUOTED = re.compile(r"\"([^\"\n]{2,120})\"|'([^'\n]{2,120})'|`([^`\n]{2,120})`")
_ROUTE = re.compile(r"(?<![\w/])/[A-Za-z0-9_.~/:{}<>*-]+")
_WORD = re.compile(r"[A-Za-z_$][\w$.-]*[\w$]|[A-Za-z_$]")
_FILE = re.compile(r"[\w-]+\.(?:[a-z]{1,5})")
_CAMEL = re.compile(r"[a-z0-9][A-Z]|[A-Z]{2}[a-z]")  # getOrder, OrderService, HTTPServer
_PASCAL_HUMPS = re.compile(r"[A-Z][a-z0-9]+[A-Z]")  # OrderService (two humps at least)
_KEBAB = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)+")
_SCREAMING = re.compile(r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+")
_PARAM = re.compile(r"[{:<*]")
_CONTENT = re.compile(r"[a-z0-9]+")
_CHAIN = re.compile(
    r"\bwho\s+(?:calls|uses|imports|depends\s+on)\b"
    r"|\bwhat\s+(?:calls|uses|breaks|depends\s+on|imports)\b"
    r"|\bcall(?:er|ers|s)\s+(?:of|to)\b"
    r"|\b(?:usages?|uses|references?|dependents|consumers)\s+of\b"
    r"|\bwhere\s+(?:is|are)\s+\S+(?:\s+\S+)?\s+(?:used|called|imported|referenced)\b"
    r"|\bimpact\b|\bbreaks?\b",
    re.IGNORECASE,
)
_STOP = frozenset(
    [
        "where",
        "what",
        "which",
        "when",
        "how",
        "who",
        "why",
        "is",
        "are",
        "was",
        "were",
        "the",
        "a",
        "an",
        "of",
        "in",
        "on",
        "at",
        "for",
        "to",
        "and",
        "or",
        "not",
        "does",
        "do",
        "did",
        "done",
        "find",
        "show",
        "me",
        "code",
        "logic",
        "function",
        "method",
        "class",
        "file",
        "defined",
        "implemented",
        "handled",
        "located",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "we",
        "our",
        "us",
        "i",
        "my",
        "you",
        "your",
        "be",
        "been",
        "being",
        "can",
        "could",
        "should",
        "would",
        "will",
        "with",
        "from",
        "by",
        "into",
        "about",
        "there",
        "here",
        "get",
        "set",
        "make",
        "made",
        "happen",
        "happens",
        "repo",
        "project",
        "app",
        "service",
        "thing",
        "things",
        "part",
    ]
)
_FILE_EXTENSIONS = frozenset(
    [
        "py",
        "js",
        "jsx",
        "ts",
        "tsx",
        "mjs",
        "cjs",
        "go",
        "rs",
        "java",
        "kt",
        "rb",
        "php",
        "cs",
        "c",
        "h",
        "cpp",
        "hpp",
        "swift",
        "scala",
        "json",
        "yaml",
        "yml",
        "toml",
        "ini",
        "cfg",
        "env",
        "md",
        "sql",
        "graphql",
        "gql",
        "proto",
        "html",
        "css",
        "scss",
        "vue",
        "svelte",
        "sh",
        "ps1",
        "xml",
        "lock",
    ]
)


def literal_terms(question: str) -> tuple[str, ...]:
    """Identifiers, routes, quoted text and file names in `question`; plain English words
    ("order", "user") are not literal, so a conceptual question yields nothing."""
    text = question[:4000]
    found: list[str] = []
    for match in _QUOTED.finditer(text):
        _add(found, next(g for g in match.groups() if g is not None))
    rest = _QUOTED.sub(" ", text)
    for match in _ROUTE.finditer(rest):
        route = _route_prefix(match.group(0))
        if route:
            _add(found, route)
    rest = _ROUTE.sub(" ", rest)
    for match in _WORD.finditer(rest):
        word = match.group(0).strip(".-")
        if _is_literal(word):
            _add(found, word)
    return tuple(found[:MAX_TERMS])


def concept_terms(question: str) -> tuple[str, ...]:
    """The question's content words, for when nothing literal is in it and no graph exists."""
    found: list[str] = []
    for word in _CONTENT.findall(question[:4000].lower()):
        if len(word) >= 4 and word not in _STOP:
            _add(found, word)
    return tuple(found[:6])


def is_chain_question(question: str) -> bool:
    """Callers, users, impact: answers that are a chain of symbols, not one place."""
    return bool(_CHAIN.search(question[:4000]))


def _is_literal(word: str) -> bool:
    if len(word) < 3 or word.lower() in _STOP:
        return False
    if "." in word:
        return bool(_FILE.fullmatch(word)) and word.rsplit(".", 1)[1] in _FILE_EXTENSIONS
    return bool(
        "_" in word.strip("_")
        or _CAMEL.search(word)
        or _PASCAL_HUMPS.search(word)
        or _KEBAB.fullmatch(word)
        or _SCREAMING.fullmatch(word)
    )


def _route_prefix(route: str) -> str:
    """`/api/orders/{id}` -> `/api/orders/`: the part before the first parameter."""
    cut = _PARAM.search(route)
    prefix = route[: cut.start()] if cut else route
    return prefix if len(prefix.strip("/")) >= 2 else ""


def _add(found: list[str], term: str) -> None:
    term = term.strip()[:_TERM_MAX]
    if term and term not in found:
        found.append(term)
