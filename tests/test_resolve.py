from cairn.model.graph import Repo, Workspace
from cairn.model.overrides import Authored
from cairn.resolve import resolve_repo

WS = Workspace(
    workspace_root="/ws", generated_at="t",
    repos=(
        Repo(id="eats", path="eats", aliases=("eats",), stack=("typescript", "nextjs")),
        Repo(id="eats-admin", path="eats-admin", aliases=("eats-admin", "admin"), stack=("typescript", "nextjs")),
        Repo(id="payments", path="payments", aliases=("payments",), stack=("go",)),
    ),
)
AUTHORED = {
    "eats": Authored(summary="Consumer marketplace app for home-cooked meals."),
    "eats-admin": Authored(summary="Restaurant-owner dashboard: menus and payouts.", aliases=("owner portal",)),
}


def _top(query: str) -> str | None:
    matches = resolve_repo(WS, AUTHORED, query)
    return matches[0].repo_id if matches else None


def test_exact_id_and_alias() -> None:
    assert _top("eats") == "eats"
    assert resolve_repo(WS, AUTHORED, "eats")[0].score == 1.0
    assert _top("owner portal") == "eats-admin"


def test_partial_and_summary_matches() -> None:
    assert _top("the admin dashboard") == "eats-admin"
    assert _top("marketplace") == "eats"
    assert _top("payouts") == "eats-admin"


def test_stack_and_fuzzy() -> None:
    assert _top("the go service") == "payments"
    assert _top("eats admn") == "eats-admin"


def test_empty_and_limit() -> None:
    assert resolve_repo(WS, AUTHORED, "the") == ()
    assert len(resolve_repo(WS, AUTHORED, "eats", limit=1)) == 1
