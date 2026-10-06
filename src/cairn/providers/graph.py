"""Read a graphify `graph.json` and answer "where is X?" from it (spec §23).

Pure Python and offline: graphify isn't needed at query time. The file is untrusted input,
so every field is checked, paths must stay inside the repo, labels are cleaned before they're
shown, and sizes are capped.
"""

import json
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path, PurePosixPath

from cairn.security.text import clean_inline

MAX_GRAPH_BYTES = 64 * 1024 * 1024
MAX_NODES = 300_000
MAX_LINKS = 1_000_000
_MAX_QUERY_TOKENS = 64
_LABEL_MAX = 120
_MIN_SCORE = 0.5
_TOKEN = re.compile(r"[a-z0-9]+")
# Identifier words: `getUserById` -> get, user, by, id; `HTTPServer` -> http, server.
_WORD = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")
_LINE = re.compile(r"L(\d{1,9})")
_STOPWORDS = frozenset(
    {
        "where",
        "what",
        "which",
        "how",
        "who",
        "is",
        "are",
        "the",
        "a",
        "an",
        "of",
        "in",
        "for",
        "to",
        "and",
        "or",
        "does",
        "do",
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
        "repo",
    }
)


@dataclass(frozen=True)
class Node:
    id: str
    label: str
    tokens: frozenset[str]
    file: str | None
    line: int | None
    callable: bool
    is_file: bool
    joined: str = ""  # the label's letters and digits, lowercased


@dataclass(frozen=True)
class Hit:
    label: str
    file: str | None
    line: int | None
    neighbours: tuple[str, ...]


class _WordIndex:
    """Which nodes carry each label word, and (remembered across queries) which label words
    each question word matches: rank() then scores only nodes that can score at all."""

    _SIMILAR_MAX = 4096

    def __init__(self, nodes: dict[str, Node]) -> None:
        self.by_token: dict[str, list[str]] = {}
        self.by_joined: dict[str, list[str]] = {}
        for node in nodes.values():
            for token in node.tokens:
                self.by_token.setdefault(token, []).append(node.id)
            if node.joined:
                self.by_joined.setdefault(node.joined, []).append(node.id)
        self._similar: dict[str, dict[str, float]] = {}
        self._lock = threading.Lock()

    def similar(self, word: str) -> dict[str, float]:
        """The label words `word` matches, with how well (see _similarity)."""
        with self._lock:
            found = self._similar.get(word)
        if found is None:
            found = {t: weight for t in self.by_token if (weight := _similarity(t, word))}
            with self._lock:
                if len(self._similar) >= self._SIMILAR_MAX:
                    self._similar.clear()
                self._similar[word] = found
        return found


@dataclass
class Graph:
    nodes: dict[str, Node] = field(default_factory=dict)
    adjacency: dict[str, list[tuple[bool, str]]] = field(default_factory=dict)  # (outgoing, other)
    _index: _WordIndex | None = field(default=None, init=False, repr=False, compare=False)

    def degree(self, node_id: str) -> int:
        return len(self.adjacency.get(node_id, ()))

    def word_index(self) -> _WordIndex:
        # Built on first use; a cached graph keeps it, so later queries skip the work.
        if self._index is None:
            self._index = _WordIndex(self.nodes)
        return self._index


GRAPH_CACHE_SIZE = 8  # graphs kept in memory by a long-running MCP server
_CACHE: "OrderedDict[str, tuple[tuple[int, int], Graph]]" = OrderedDict()
_CACHE_LOCK = threading.Lock()


def load_graph_cached(path: Path) -> Graph | None:
    """load_graph(), reused until the file's size or mtime changes (a rebuild): parsing a large
    graph takes ~0.4 s, a cache hit microseconds. Bounded LRU; thread-safe."""
    try:
        info = path.stat()
    except OSError:
        return None
    stamp = (info.st_mtime_ns, info.st_size)
    key = str(path)
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit is not None and hit[0] == stamp:
            _CACHE.move_to_end(key)
            return hit[1]
    graph = load_graph(path)
    if graph is None:
        return None
    with _CACHE_LOCK:
        _CACHE[key] = (stamp, graph)
        _CACHE.move_to_end(key)
        while len(_CACHE) > GRAPH_CACHE_SIZE:
            _CACHE.popitem(last=False)
    return graph


def clear_graph_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def cached_graphs() -> int:
    return len(_CACHE)


def load_graph(path: Path, *, max_bytes: int = MAX_GRAPH_BYTES) -> Graph | None:
    try:
        if path.stat().st_size > max_bytes:
            return None
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError, RecursionError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
        return None
    graph = Graph()
    for raw in data["nodes"][:MAX_NODES]:
        node = _node(raw)
        if node is not None:
            graph.nodes[node.id] = node
    links = data.get("links") if isinstance(data.get("links"), list) else data.get("edges")
    for raw in (links if isinstance(links, list) else [])[:MAX_LINKS]:
        if not isinstance(raw, dict):
            continue
        source, target = raw.get("source"), raw.get("target")
        if (
            isinstance(source, str)
            and isinstance(target, str)
            and source in graph.nodes
            and target in graph.nodes
        ):
            graph.adjacency.setdefault(source, []).append((True, target))
            graph.adjacency.setdefault(target, []).append((False, source))
    return graph


def rank(graph: Graph, question: str, limit: int) -> list[Hit]:
    words = _query_tokens(question)
    if not words:
        return []
    index = graph.word_index()
    # Label word -> the question words it answers. Only nodes holding one of those label words,
    # or whose whole label is a question word, can score above zero.
    memo: dict[str, dict[str, float]] = {}
    candidates: set[str] = set()
    for word in words:
        candidates.update(index.by_joined.get(word, ()))
        for token, weight in index.similar(word).items():
            memo.setdefault(token, {})[word] = weight
            candidates.update(index.by_token[token])
    scored: list[tuple[float, int, str, str]] = []
    for node_id in candidates:
        node = graph.nodes[node_id]
        for token in node.tokens:
            memo.setdefault(token, {})  # answers none of the question's words
        score = _score(node, words, memo)
        if score >= _MIN_SCORE:
            scored.append((-score, -graph.degree(node.id), node.label, node.id))
    scored.sort()
    return [_hit(graph, graph.nodes[node_id]) for *_, node_id in scored[:limit]]


def hubs(graph: Graph, top: int) -> list[str]:
    """The most connected code symbols: where a newcomer should start reading."""
    # Symbols with a source file: an import node (`numpy`) has no place in the repo to read.
    candidates = [n for n in graph.nodes.values() if n.file and not n.is_file]
    candidates.sort(key=lambda n: (-graph.degree(n.id), n.label))
    return [n.label for n in candidates[:top] if graph.degree(n.id) > 0]


def _node(raw: object) -> Node | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
        return None
    label_raw = raw.get("label")
    if not isinstance(label_raw, str) or not label_raw.strip():
        return None
    label = clean_inline(label_raw, _LABEL_MAX)
    file = _safe_file(raw.get("source_file"))
    location = raw.get("source_location")
    match = _LINE.fullmatch(location) if isinstance(location, str) else None
    is_file = file is not None and label == PurePosixPath(file).name
    return Node(
        id=raw["id"],
        label=label,
        tokens=frozenset(w.lower() for w in _WORD.findall(label)),
        joined="".join(_TOKEN.findall(label.lower())),
        file=file,
        line=int(match.group(1)) if match else None,
        callable=bool(raw.get("_callable")) or label.endswith(")"),
        is_file=is_file,
    )


def _safe_file(value: object) -> str | None:
    """A repo-relative POSIX path, or None for anything absolute or escaping the repo."""
    if not isinstance(value, str) or not value or len(value) > 500:
        return None
    path = value.replace("\\", "/")
    parts = path.split("/")
    if path.startswith("/") or re.match(r"[A-Za-z]:", path) or ".." in parts:
        return None
    return clean_inline(path, 300)


def _query_tokens(question: str) -> frozenset[str]:
    found: list[str] = []
    for token in _TOKEN.finditer(question[:20_000].lower()):
        word = token.group(0)
        if word not in _STOPWORDS and len(word) >= 2 and word not in found:
            found.append(word)
            if len(found) >= _MAX_QUERY_TOKENS:
                break
    return frozenset(found)


def _score(node: Node, words: frozenset[str], memo: dict[str, dict[str, float]]) -> float:
    """Plan Task 1: the whole label (1.0), else exact (1.0), shared-stem (0.75) and fuzzy
    (0.6) word matches, weighted by how much of the label and of the question they cover."""
    if not node.tokens:
        return 0.0
    if node.joined and node.joined in words:
        score = 1.0
    else:
        per_token = [_matches(token, words, memo) for token in node.tokens]
        matched = sum(max(m.values(), default=0.0) for m in per_token)
        if not matched:
            return 0.0
        covered = len({w for m in per_token for w in m})
        score = 0.7 * matched / len(node.tokens) + 0.3 * covered / len(words)
    if node.callable:
        score += 0.05
    if node.is_file:
        score -= 0.1
    return score


def _matches(
    token: str, words: frozenset[str], memo: dict[str, dict[str, float]]
) -> dict[str, float]:
    """The question words this label word answers, with how well; rank() fills `memo`."""
    found = memo.get(token)
    if found is None:
        found = {w: weight for w in words if (weight := _similarity(token, w))}
        memo[token] = found
    return found


def _similarity(token: str, word: str) -> float:
    if token == word:
        return 1.0
    short, long = sorted((len(token), len(word)))
    if short < 4:
        return 0.0
    prefix = 0
    for a, b in zip(token, word, strict=False):
        if a != b:
            break
        prefix += 1
    if prefix >= max(4, 0.75 * short):
        return 0.75
    if short < 5 or 2 * short / (short + long) < 0.8:
        return 0.0
    matcher = SequenceMatcher(None, token, word)
    # quick_ratio() bounds ratio() from above and is far cheaper: most pairs stop there.
    return 0.6 if matcher.quick_ratio() >= 0.8 and matcher.ratio() >= 0.8 else 0.0


def _hit(graph: Graph, node: Node) -> Hit:
    links = sorted(graph.adjacency.get(node.id, ()), key=lambda link: (not link[0], link[1]))
    neighbours: list[str] = []
    for _, other in links:
        label = graph.nodes[other].label
        if not graph.nodes[other].is_file and label not in neighbours:
            neighbours.append(label)
        if len(neighbours) == 3:
            break
    return Hit(label=node.label, file=node.file, line=node.line, neighbours=tuple(neighbours))
