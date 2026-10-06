"""0.7 B2: the offline locate benchmark — no agent, no cost."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cairn.bench.locate_eval import (
    LocateQuery,
    evaluate,
    load_locate_set,
    prepare_locate_workspace,
    summarize,
)
from cairn.cli import app
from cairn.errors import CairnError
from cairn.locate.hybrid import run_locator
from cairn.locate.model import LocateHit, LocateResult
from cairn.locate.workspace import fan_out
from cairn.providers.meta import deep_dir

REPOS = {
    "shop": {
        "src/orders.py": "def getOrderById(order_id):\n    return order_id\n",
        "src/api.py": "from src.orders import getOrderById\n\ngetOrderById(1)\n",
        "src/money.py": "def charge(card):\n    return card\n",
    },
    "mail": {"src/notify.py": "def sendReceipt(email):\n    return email\n"},
}
GRAPHS = {
    "shop": [
        ("getOrderById()", "src/orders.py", 1),
        ("charge()", "src/money.py", 1),
    ],
    "mail": [("sendReceipt()", "src/notify.py", 1)],
}
KEY = """\
split: dev
queries:
  - {id: q-lit, category: literal, repo: shop, question: "where is getOrderById defined",
     answers: [shop/src/orders.py]}
  - {id: q-voc, category: vocabulary, repo: shop, question: "where do we charge the card",
     answers: [shop/src/money.py]}
  - {id: q-x, category: cross-repo, repo: shop, question: "where is sendReceipt",
     answers: [mail/src/notify.py]}
  - {id: q-miss, category: broad, repo: shop, question: "where is the warehouse",
     answers: [shop/src/api.py]}
"""


def _suite(tmp_path: Path, *, graphs: bool = True) -> Path:
    suite = tmp_path / "suite"
    for repo, files in REPOS.items():
        root = suite / "fixtures" / repo
        root.mkdir(parents=True)
        (root / ".fixture-repo").write_text("", encoding="utf-8")
        for rel, text in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text, encoding="utf-8")
    (suite / "suite.yaml").write_text(
        "name: tiny\nworkspace: fixtures\nrelated_repos_doc: r.md\ntasks: []\n", encoding="utf-8"
    )
    (suite / "locate.yaml").write_text(KEY, encoding="utf-8")
    return suite


def _write_graphs(ws: Path) -> None:
    for repo, symbols in GRAPHS.items():
        out = deep_dir(ws, repo) / "graphify-out"
        out.mkdir(parents=True, exist_ok=True)
        nodes = [
            {"id": f"{repo}{i}", "label": s, "source_file": f, "source_location": f"L{line}"}
            for i, (s, f, line) in enumerate(symbols)
        ]
        (out / "graph.json").write_text(json.dumps({"nodes": nodes, "links": []}), "utf-8")


def test_a_key_is_validated(tmp_path: Path) -> None:
    suite = _suite(tmp_path)
    assert [q.id for q in load_locate_set(suite).queries] == ["q-lit", "q-voc", "q-x", "q-miss"]
    (suite / "locate.yaml").write_text(
        "split: dev\nqueries:\n  - {id: a, category: vibes, repo: shop, question: q, answers: [x]}\n",
        encoding="utf-8",
    )
    with pytest.raises(CairnError):
        load_locate_set(suite)


def test_the_workspace_is_materialised_once_and_its_graphs_loaded(tmp_path: Path) -> None:
    suite = _suite(tmp_path)
    cache = tmp_path / "cache"
    ws, graphs = prepare_locate_workspace(suite, cache, provider=None)
    assert sorted(graphs) == ["mail", "shop"] and graphs["shop"] is None
    _write_graphs(ws)
    again, graphs = prepare_locate_workspace(suite, cache, provider=None)
    assert again == ws and graphs["shop"] is not None and len(graphs["shop"].nodes) == 2


def test_each_locator_is_scored_per_query(tmp_path: Path) -> None:
    suite = _suite(tmp_path)
    ws, _ = prepare_locate_workspace(suite, tmp_path / "cache", provider=None)
    _write_graphs(ws)
    ws, graphs = prepare_locate_workspace(suite, tmp_path / "cache", provider=None)
    outcomes = evaluate(ws, graphs, load_locate_set(suite), ("grep", "graph", "hybrid"))
    rank = {(o.query_id, o.mode): o.rank for o in outcomes}
    assert rank[("q-lit", "grep")] == 1 and rank[("q-lit", "hybrid")] == 1
    assert rank[("q-voc", "graph")] == 1 and rank[("q-voc", "hybrid")] == 1
    assert rank[("q-x", "grep")] == 1  # cross-repo questions search the whole workspace
    assert rank[("q-miss", "hybrid")] is None
    assert all(o.tokens >= 0 and o.ms >= 0 for o in outcomes)
    route = {(o.query_id, o.mode): o.route for o in outcomes}
    assert route[("q-lit", "hybrid")] == "grep" and route[("q-voc", "hybrid")] == "graph"


def test_the_summary_is_a_table_per_split_locator_and_category(tmp_path: Path) -> None:
    suite = _suite(tmp_path)
    ws, _ = prepare_locate_workspace(suite, tmp_path / "cache", provider=None)
    _write_graphs(ws)
    ws, graphs = prepare_locate_workspace(suite, tmp_path / "cache", provider=None)
    text = summarize(evaluate(ws, graphs, load_locate_set(suite), ("grep", "hybrid")))
    assert "| dev | hybrid | literal | 1 | 1.00 |" in text
    assert "| dev | hybrid | all | 4 |" in text


def test_the_cli_writes_a_report(tmp_path: Path) -> None:
    suite = _suite(tmp_path)
    out = tmp_path / "out"
    result = CliRunner().invoke(
        app,
        [
            "bench-locate",
            str(suite),
            "--no-build",
            "--cache",
            str(tmp_path / "c"),
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert any(p.suffix == ".md" for p in out.iterdir()) and "| dev | hybrid |" in result.output


# -- the pieces it is built from --------------------------------------------------------------


def test_run_locator_modes(tmp_path: Path) -> None:
    suite = _suite(tmp_path)
    ws, _ = prepare_locate_workspace(suite, tmp_path / "cache", provider=None)
    shop = ws / "shop"
    grep_only = run_locator("grep", shop, "where do we charge the card", None)
    assert grep_only.route == "grep" and grep_only.hits[0].file == "src/money.py"
    assert run_locator("graph", shop, "anything", None).hits == ()
    with pytest.raises(ValueError):
        run_locator("magic", shop, "q", None)


def test_fan_out_interleaves_repos_by_rank() -> None:
    def hit(file: str, score: float) -> LocateHit:
        return LocateHit(file=file, line=1, why="w", source="grep", score=score)

    merged = fan_out(
        {
            "a": LocateResult((hit("x.py", 1.0), hit("y.py", 0.5)), "grep", "r"),
            "b": LocateResult((hit("z.py", 3.0),), "grep", "r"),
        },
        limit=3,
    )
    assert [(h.repo, h.file) for h in merged] == [("b", "z.py"), ("a", "x.py"), ("a", "y.py")]


def test_queries_name_workspace_paths() -> None:
    with pytest.raises(ValueError):
        LocateQuery(id="a", category="literal", repo="shop", question="q", answers=())
