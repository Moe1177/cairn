"""0.7 B3: the MCP `query` tool answers with the tuned locator — grep first, the code graph as a
backstop — says which one answered, and looks in the other repos a question is about."""

import json
from pathlib import Path

import pytest

from cairn import providers
from cairn.bench.workspace import materialize
from cairn.emit import write_outputs
from cairn.mcp_server import query as query_module
from cairn.mcp_server import tools
from cairn.providers.graphify import GraphifyProvider
from cairn.providers.meta import META_FILE, deep_dir
from cairn.scan import scan_workspace

REPOS = {
    "app": {
        "auth.py": "def login(user):\n    return check(user)\n",
        "orders/create.py": "def place(order):\n    return order\n",
    },
    "billing": {
        "charge.py": "def charge(card):\n    return card\n",
        "refunds.py": "def issue_refund(payment):\n    return payment\n",
    },
}


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    src = tmp_path / "src"
    for repo, files in REPOS.items():
        (src / repo).mkdir(parents=True)
        (src / repo / ".fixture-repo").write_text("", encoding="utf-8")
        for rel, text in files.items():
            (src / repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (src / repo / rel).write_text(text, encoding="utf-8")
    root = materialize(src, tmp_path / "ws").resolve()
    write_outputs(root, scan_workspace(root))
    # No graphify on this machine unless a test builds an index by hand.
    missing = GraphifyProvider(executable=str(tmp_path / "no-graphify"))
    monkeypatch.setattr(providers, "default_provider", lambda: missing)
    return root


def _relate(ws: Path) -> None:
    (ws / ".cairn" / "relations.yaml").write_text(
        "edges:\n  - {from: app, to: billing, type: calls_http, note: checkout}\n",
        encoding="utf-8",
    )
    write_outputs(ws, scan_workspace(ws))


def _index(ws: Path, repo: str, symbols: list[tuple[str, str, int]], *, head: str) -> None:
    out = deep_dir(ws, repo)
    (out / "graphify-out").mkdir(parents=True, exist_ok=True)
    nodes = [
        {"id": f"n{i}", "label": s, "source_file": f, "source_location": f"L{line}"}
        for i, (s, f, line) in enumerate(symbols)
    ]
    (out / "graphify-out" / "graph.json").write_text(
        json.dumps({"nodes": nodes, "links": []}), encoding="utf-8"
    )
    meta = {"provider": "graphify", "head_sha": head, "fingerprint": "x", "nodes": len(nodes)}
    (out / META_FILE).write_text(json.dumps(meta), encoding="utf-8")


def test_query_answers_without_any_deep_index_and_names_the_locator(ws: Path) -> None:
    answer = tools.query_text(ws, "app", "where is login defined?")
    assert "grep" in answer.splitlines()[0]
    assert "auth.py:1" in answer


def test_a_repo_named_in_the_question_is_searched_too(ws: Path) -> None:
    answer = tools.query_text(ws, "app", "where does billing issue_refund?")
    assert "billing/refunds.py:1" in answer


def test_related_repos_are_searched_when_the_repo_has_nothing(ws: Path) -> None:
    _relate(ws)
    answer = tools.query_text(ws, "app", "where is issue_refund defined?")
    assert "billing/refunds.py:1" in answer and "related" in answer


def test_related_repos_are_not_searched_when_the_repo_answers(ws: Path) -> None:
    _relate(ws)
    answer = tools.query_text(ws, "app", "where is login defined?")
    assert "billing" not in answer


def test_the_graph_answers_when_grep_cannot_and_says_when_stale(ws: Path) -> None:
    _index(ws, "app", [("login()", "auth.py", 1)], head="0000000")
    answer = tools.query_text(ws, "app", "logins")  # no text match; the graph's fuzzy name does
    assert "graph" in answer.splitlines()[0] and "login()" in answer and "auth.py:1" in answer
    assert "may be stale" in answer and "cairn deep build app" in answer


def test_an_incomplete_deep_index_says_rebuild(ws: Path) -> None:
    _index(ws, "app", [("login()", "auth.py", 1)], head="0000000")
    (deep_dir(ws, "app") / "graphify-out" / "graph.json").unlink()
    answer = tools.query_text(ws, "app", "where is login defined?")
    assert "auth.py:1" in answer and "incomplete" in answer and "cairn deep build app" in answer


def test_nothing_found_lists_the_folders(ws: Path) -> None:
    answer = tools.query_text(ws, "app", "where is the warehouse robot")
    assert answer.startswith("Nothing in app matches") and "Start from" in answer


def test_answers_stay_inside_the_line_cap(ws: Path) -> None:
    for i in range(60):
        (ws / "app" / f"m{i}.py").write_text("import login_helpers\n", encoding="utf-8")
    answer = tools.query_text(ws, "app", "where is login_helpers used")
    assert len(answer.splitlines()) <= tools.MAX_LINES + 4


def test_the_query_module_is_where_staleness_is_cached() -> None:
    assert query_module.STALE_TTL > 0
