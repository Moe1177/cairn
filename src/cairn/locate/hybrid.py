"""Route a "where is X?" question to grep, the code graph, or both.

grep when the question carries the code's own words (an identifier, a route, a message); the
graph when it doesn't, when the answer is a chain (who calls, what breaks), or when grep finds
too much. Each answer says which locator answered and why. Thresholds are tuned by the offline
locate benchmark (plan B2).
"""

from pathlib import Path

from cairn.discover.files import read_text
from cairn.locate.grep import grep_locate
from cairn.locate.model import GrepResult, LocateHit, LocateResult
from cairn.locate.terms import concept_terms, is_chain_question, literal_terms
from cairn.providers.graph import Graph, rank

BROAD_FILES = 12  # grep matching more files than this is "too broad" when a graph can help


def hybrid_locate(
    repo_root: Path,
    question: str,
    graph: Graph | None,
    *,
    graph_stale: bool = False,
    limit: int = 10,
) -> LocateResult:
    literal = literal_terms(question)
    chain = is_chain_question(question)
    grep = grep_locate(repo_root, literal, limit=limit) if literal else None
    found = grep is not None and bool(grep.hits)
    if found and grep is not None and not chain and grep.files_matched <= BROAD_FILES:
        return LocateResult(grep.hits, "grep", f"literal: {', '.join(literal)}", grep.truncated)
    if graph is not None:
        graph_hits = _graph_hits(repo_root, graph, question, limit)
        reason = _why_graph(literal, chain, grep) + (
            "; deep index may be stale" if graph_stale else ""
        )
        if found and grep is not None:
            return LocateResult(
                _merge(grep.hits, graph_hits, limit), "grep+graph", reason, grep.truncated
            )
        if graph_hits:
            return LocateResult(graph_hits, "graph", reason)
    if found and grep is not None:
        return LocateResult(grep.hits, "grep", f"literal: {', '.join(literal)}", grep.truncated)
    words = concept_terms(question)
    if not words:
        return LocateResult((), "none", "nothing in the question to search for")
    loose = grep_locate(repo_root, words, limit=limit)
    return LocateResult(loose.hits, "grep", f"words: {', '.join(words)}", loose.truncated)


def _why_graph(literal: tuple[str, ...], chain: bool, grep: GrepResult | None) -> str:
    if chain:
        return "chain question"
    if not literal:
        return "no literal words in the question"
    if grep is None or not grep.hits:
        return f"grep found no {', '.join(literal)}"
    return f"grep too broad ({grep.files_matched} files)"


def _graph_hits(root: Path, graph: Graph, question: str, limit: int) -> tuple[LocateHit, ...]:
    """Graph symbols, kept only where the file exists and the line is inside it: an index built
    before an edit or a delete must not send anyone to a place that isn't there."""
    hits: list[LocateHit] = []
    lengths: dict[str, int | None] = {}
    for hit in rank(graph, question, limit * 2):
        if not hit.file:
            continue
        if hit.file not in lengths:
            text = read_text(root / hit.file)
            lengths[hit.file] = None if text is None else len(text.splitlines())
        size = lengths[hit.file]
        if size is None:
            continue
        near = f" (near: {', '.join(hit.neighbours)})" if hit.neighbours else ""
        hits.append(
            LocateHit(
                file=hit.file,
                line=hit.line if hit.line and hit.line <= size else None,
                why=f"graph: {hit.label}{near}",
                source="graph",
                symbol=hit.label,
            )
        )
        if len(hits) == limit:
            break
    return tuple(hits)


def _merge(
    grep_hits: tuple[LocateHit, ...], graph_hits: tuple[LocateHit, ...], limit: int
) -> tuple[LocateHit, ...]:
    """Places both locators found first (grep's line, the graph's symbol), then the rest of
    each, alternating."""
    by_file = {hit.file: hit for hit in reversed(graph_hits)}  # best graph hit per file
    both = [
        LocateHit(
            file=hit.file,
            line=hit.line,
            why=f"{hit.why}; {by_file[hit.file].why}",
            source="grep+graph",
            symbol=by_file[hit.file].symbol,
            score=hit.score,
        )
        for hit in grep_hits
        if hit.file in by_file
    ]
    agreed = {hit.file for hit in both}
    grep_only = [hit for hit in grep_hits if hit.file not in agreed]
    graph_only = [hit for hit in graph_hits if hit.file not in agreed]
    rest: list[LocateHit] = []
    for pair in zip(grep_only, graph_only, strict=False):
        rest.extend(pair)
    shorter = min(len(grep_only), len(graph_only))
    rest.extend(grep_only[shorter:] or graph_only[shorter:])
    return tuple([*both, *rest][:limit])


MODES = ("grep", "graph", "hybrid")


def run_locator(
    mode: str,
    repo_root: Path,
    question: str,
    graph: Graph | None,
    *,
    graph_stale: bool = False,
    limit: int = 10,
) -> LocateResult:
    """One locator on its own (`grep`, `graph`) or the router (`hybrid`): what the locate
    benchmark compares."""
    if mode == "hybrid":
        return hybrid_locate(repo_root, question, graph, graph_stale=graph_stale, limit=limit)
    if mode == "graph":
        hits = _graph_hits(repo_root, graph, question, limit) if graph is not None else ()
        return LocateResult(hits, "graph", "graph only")
    if mode == "grep":
        literal = literal_terms(question)
        if literal:
            found = grep_locate(repo_root, literal, limit=limit)
            if found.hits:
                return LocateResult(found.hits, "grep", "literal", found.truncated)
        words = concept_terms(question)
        loose = grep_locate(repo_root, words, limit=limit)
        return LocateResult(loose.hits, "grep", "words", loose.truncated)
    raise ValueError(f"unknown locator {mode!r} (choose from {', '.join(MODES)})")
