"""Answer "where is X?" with grep first and the code graph as a backstop.

Measured by the offline locate benchmark (plan B2, `cairn bench-locate`): grep matched or beat
the graph on every kind of question, and sending questions to the graph instead lost answers
(graphify's code graph holds functions and classes, not routes, constants or messages, and ranks
by name), and filling grep's empty places with graph hits added tokens but no answers. So grep
answers; for a chain question (who calls X) the file defining X goes last; the graph names the
symbol on grep hits it agrees with, and answers alone only when grep finds nothing. Every answer
says which locator answered and why.
"""

from pathlib import Path

from cairn.discover.files import read_text
from cairn.locate.grep import grep_locate
from cairn.locate.model import GrepResult, LocateHit, LocateResult
from cairn.locate.terms import concept_terms, is_chain_question, literal_terms
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
        return LocateResult(hits, "grep" if hits else "none", reason, found.truncated)
    graph_hits = _graph_hits(repo_root, graph, question, limit)
    stale = "; deep index may be stale" if graph_stale else ""
    if not hits:
        if graph_hits:
            return LocateResult(graph_hits, "graph", f"grep found nothing ({reason}){stale}")
        return LocateResult((), "none", reason)
    return LocateResult(_agree(hits, graph_hits), "grep", reason, found.truncated)


def _grep(root: Path, question: str, limit: int) -> tuple[GrepResult, str]:
    """The question's literal terms; failing those (none, or none in the code), its words."""
    literal = literal_terms(question)
    if literal:
        found = grep_locate(root, literal, limit=limit)
        if found.hits:
            return found, f"literal: {', '.join(literal)}"
    words = concept_terms(question)
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


def _agree(
    grep_hits: tuple[LocateHit, ...], graph_hits: tuple[LocateHit, ...]
) -> tuple[LocateHit, ...]:
    """grep's hits as they are, each naming the graph's symbol where the graph agrees. The graph
    adds no places of its own here: on bench-locate that added tokens and no answers."""
    by_file = {hit.file: hit for hit in reversed(graph_hits)}  # best graph hit per file
    return tuple(
        LocateHit(
            file=hit.file,
            line=hit.line,
            why=hit.why,
            source="grep+graph",
            symbol=by_file[hit.file].symbol,
            score=hit.score,
        )
        if hit.file in by_file
        else hit
        for hit in grep_hits
    )


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
