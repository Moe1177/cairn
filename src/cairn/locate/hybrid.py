"""Answer "where is X?" with grep first and the code graph as a backstop.

Measured by the offline locate benchmark (plan B2, `cairn bench-locate`): grep matched or beat
the graph on every kind of question, and sending questions to the graph instead lost answers
(graphify's code graph holds functions and classes, not routes, constants or messages, and ranks
by name), and filling grep's empty places with graph hits added tokens but no answers. So grep
answers; for a chain question (who calls X) the file defining X goes last; a fresh graph names
the symbol each grep line sits in, and the graph answers alone only when grep finds nothing (a
stale one says so). Every answer says which locator answered and why.
"""

from dataclasses import replace
from pathlib import Path

from cairn.discover.files import read_text
from cairn.locate.grep import grep_locate
from cairn.locate.model import GrepResult, LocateHit, LocateResult
from cairn.locate.terms import concept_terms, is_chain_question, is_weak, literal_terms
from cairn.providers.graph import Graph, rank


def hybrid_locate(
    repo_root: Path,
    question: str,
    graph: Graph | None,
    *,
    graph_stale: bool = False,
    limit: int = 10,
) -> LocateResult:
    found, reason = _grep(repo_root, question, limit)
    hits = found.hits
    if is_chain_question(question):
        hits = _users_first(hits)
        reason = f"chain question; {reason}"
    if graph is None:
        return LocateResult(
            hits, "grep" if hits else "none", reason, found.truncated, found.partial
        )
    if not hits:
        graph_hits = _graph_hits(repo_root, graph, question, limit)
        if graph_hits:
            stale = "; deep index may be stale" if graph_stale else ""
            why = f"grep found nothing ({reason}){stale}"
            return LocateResult(graph_hits, "graph", why, partial=found.partial)
        return LocateResult((), "none", reason, partial=found.partial)
    if graph_stale:  # its symbols may have moved or gone: grep's lines stand alone
        return LocateResult(hits, "grep", reason, found.truncated, found.partial)
    return LocateResult(_agree(hits, graph), "grep", reason, found.truncated, found.partial)


def _grep(root: Path, question: str, limit: int) -> tuple[GrepResult, str]:
    """The question's literal terms; failing those (none, or none in the code), its words."""
    literal = literal_terms(question)
    if any(not is_weak(term) for term in literal):
        found = grep_locate(root, literal, limit=limit)
        if found.hits:
            return found, f"literal: {', '.join(literal)}"
    # Only weak literals ("real-time"), none found, or none at all: the question's words too.
    words = tuple(dict.fromkeys([*(t for t in literal if is_weak(t)), *concept_terms(question)]))
    if not words:
        return GrepResult((), 0, False), "nothing in the question to search for"
    return grep_locate(root, words, limit=limit), f"words: {', '.join(words)}"


def _users_first(hits: tuple[LocateHit, ...]) -> tuple[LocateHit, ...]:
    """Who calls X is answered by the files using X: the one defining it goes last."""
    return tuple(sorted(hits, key=lambda hit: "(definition)" in hit.why))


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


def _agree(grep_hits: tuple[LocateHit, ...], graph: Graph) -> tuple[LocateHit, ...]:
    """grep's hits as they are, each naming the graph symbol its line sits in. The graph adds no
    places of its own here: on bench-locate that added tokens and no answers."""
    named = []
    for hit in grep_hits:
        symbol = graph.enclosing(hit.file, hit.line) if hit.line else None
        named.append(
            replace(hit, source="grep+graph", symbol=symbol) if symbol is not None else hit
        )
    return tuple(named)


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
