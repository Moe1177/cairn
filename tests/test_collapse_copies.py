"""0.7.1 second review: collapsing copies of one app in `query` answers."""

from cairn.locate.model import LocateHit
from cairn.mcp_server.query import collapse_copies
from cairn.model.graph import Confidence, Edge, EdgeType, Repo, Workspace


def _ws(repos: list[str], copies: list[tuple[str, str, Confidence]]) -> Workspace:
    edges = tuple(
        Edge(source=a, target=b, type=EdgeType.MIRRORS, confidence=c, score=1.0)
        for a, b, c in copies
    )
    return Workspace(
        workspace_root="/w",
        generated_at="t",
        repos=tuple(Repo(id=r, path=r) for r in repos),
        edges=edges,
    )


def _hit(repo: str, file: str, line: int | None, symbol: str | None = None) -> LocateHit:
    return LocateHit(file=file, line=line, why="w", source="grep", symbol=symbol, repo=repo)


def _lines(hits: tuple[LocateHit, ...]) -> list[tuple[str | None, str, int | None, tuple]]:
    return [(h.repo, h.file, h.line, h.also) for h in hits]


def test_hits_of_one_repo_are_never_merged() -> None:
    ws = _ws(["a"], [])
    hits = (_hit("a", "x.py", None, "foo()"), _hit("a", "x.py", None, "bar()"))
    assert collapse_copies(hits, ws, asked="a") == hits


def test_places_without_a_line_are_never_merged() -> None:
    ws = _ws(["a", "b"], [("a", "b", Confidence.EXTRACTED)])
    hits = (_hit("a", "x.py", None, "foo()"), _hit("b", "x.py", None, "bar()"))
    assert collapse_copies(hits, ws, asked="a") == hits


def test_unconfirmed_copies_are_not_merged() -> None:
    """A shared package name alone only suggests a copy (ambiguous): two apps stay two."""
    ws = _ws(["web", "admin"], [("web", "admin", Confidence.AMBIGUOUS)])
    hits = (_hit("web", "src/index.ts", 1), _hit("admin", "src/index.ts", 1))
    assert collapse_copies(hits, ws, asked="web") == hits


def test_the_asked_repo_speaks_for_its_copies_and_they_are_listed_in_order() -> None:
    ws = _ws(
        ["admin", "a-2024", "a-2025"],
        [("admin", "a-2024", Confidence.EXTRACTED), ("admin", "a-2025", Confidence.EXTRACTED)],
    )
    hits = (_hit("a-2025", "s.ts", 3), _hit("a-2024", "s.ts", 3), _hit("admin", "s.ts", 3))
    assert _lines(collapse_copies(hits, ws, asked="admin")) == [
        ("admin", "s.ts", 3, ("a-2024", "a-2025"))
    ]


def test_same_paths_in_unrelated_repos_stay_apart() -> None:
    ws = _ws(["a", "b"], [])
    hits = (_hit("a", "src/index.ts", 1), _hit("b", "src/index.ts", 1))
    assert collapse_copies(hits, ws, asked="a") == hits
