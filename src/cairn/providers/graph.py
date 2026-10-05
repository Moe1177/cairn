"""Read a graphify `graph.json` and answer "where is X?" from it (spec §23).

Pure Python and offline: graphify isn't needed at query time. The file is untrusted input,
so every field is checked, paths must stay inside the repo, labels are cleaned before they're
shown, and sizes are capped.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from cairn.security.text import clean_inline

MAX_GRAPH_BYTES = 64 * 1024 * 1024
MAX_NODES = 300_000
MAX_LINKS = 1_000_000
_MAX_QUERY_TOKENS = 64
_LABEL_MAX = 120
_MIN_SCORE = 0.5
_TOKEN = re.compile(r"[a-z0-9]+")
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


@dataclass(frozen=True)
class Hit:
    label: str
    file: str | None
    line: int | None
    neighbours: tuple[str, ...]


@dataclass
class Graph:
    nodes: dict[str, Node] = field(default_factory=dict)
    adjacency: dict[str, list[tuple[bool, str]]] = field(default_factory=dict)  # (outgoing, other)

    def degree(self, node_id: str) -> int:
        return len(self.adjacency.get(node_id, ()))


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
    scored: list[tuple[float, int, str, str]] = []
    for node in graph.nodes.values():
        score = _score(node, words)
        if score >= _MIN_SCORE:
            scored.append((-score, -graph.degree(node.id), node.label, node.id))
    scored.sort()
    return [_hit(graph, graph.nodes[node_id]) for *_, node_id in scored[:limit]]


def hubs(graph: Graph, top: int) -> list[str]:
    """The most connected code symbols: where a newcomer should start reading."""
    candidates = [n for n in graph.nodes.values() if not n.is_file]
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
        tokens=frozenset(_TOKEN.findall(label.lower())),
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


def _score(node: Node, words: frozenset[str]) -> float:
    if not node.tokens:
        return 0.0
    shared = node.tokens & words
    if not shared:
        partial = sum(
            1
            for t in node.tokens
            if len(t) >= 4
            and any(len(w) >= 4 and (t.startswith(w) or w.startswith(t)) for w in words)
        )
        if not partial:
            return 0.0
        score = 0.55 * partial / len(node.tokens)
    else:
        score = 0.7 * len(shared) / len(node.tokens) + 0.3 * len(shared) / len(words)
    if node.callable:
        score += 0.05
    if node.is_file:
        score -= 0.1
    return score


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
