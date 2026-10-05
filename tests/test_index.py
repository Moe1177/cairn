from cairn.model.graph import Confidence, Edge, EdgeType, Repo, Workspace
from cairn.model.overrides import Authored
from cairn.render.index import INDEX_TITLE, one_liner, render_index, repo_line
from cairn.render.tokens import estimate_tokens


def _repo(i: str, **kw) -> Repo:
    return Repo(id=i, path=i, **kw)


def test_repo_line_format_and_budget() -> None:
    repo = _repo("shop-admin", aliases=("shop-admin", "admin", "owner portal", "extra"), stack=("typescript", "nextjs"))
    line = repo_line(repo, Authored(summary="Restaurant-owner dashboard for shopapp: menus, orders, payouts. More."))
    assert line == "- shop-admin (admin, owner portal): Restaurant-owner dashboard for shopapp: menus, orders, payouts · nextjs"
    assert estimate_tokens(line) <= 30


def test_one_liner_fallbacks_and_cap() -> None:
    assert one_liner(_repo("a", readme_excerpt="Short readme. Second."), None) == "Short readme"
    assert one_liner(_repo("a"), None) == "no summary yet"
    long = one_liner(_repo("a"), Authored(summary="x" * 200))
    assert len(long) == 60 and long.endswith("…")


def test_render_index_lists_every_repo_under_threshold() -> None:
    ws = Workspace(workspace_root="/ws", generated_at="t", repos=(_repo("a"), _repo("b", stack=("go",))))
    text = render_index(ws, {})
    lines = text.splitlines()
    assert lines[0] == INDEX_TITLE
    assert "`/ws`" in lines[1] and ".cairn/cards/<repo>.md" in lines[1]
    assert "- a: no summary yet" in lines
    assert "- b: no summary yet · go" in lines
    assert text.endswith("\n")


def test_render_index_groups_above_threshold() -> None:
    repos = tuple(_repo(f"svc{i:02d}") for i in range(8))
    edges = (
        Edge(source="svc00", target="svc01", type=EdgeType.SHARES_DB, confidence=Confidence.INFERRED, score=0.6),
        Edge(source="svc02", target="svc01", type=EdgeType.DEPENDS_ON_PACKAGE, confidence=Confidence.EXTRACTED, score=1.0),
        Edge(source="svc03", target="svc04", type=EdgeType.MENTIONS, confidence=Confidence.AMBIGUOUS, score=0.1),
    )
    ws = Workspace(workspace_root="/ws", generated_at="t", repos=repos, edges=edges)
    text = render_index(ws, {}, threshold=5)
    assert "- group svc01 (3 repos): svc00, svc01, svc02" in text
    assert "- ungrouped (5 repos): svc03, svc04, svc05, svc06, svc07" in text
