"""0.7 A2: the MCP server keeps deep graphs in memory between queries."""

import json
import time
from pathlib import Path

import pytest

from cairn.providers import graph as graph_module


def _graph(path: Path, label: str) -> None:
    nodes = [{"id": "a", "label": label, "source_file": "a.py", "source_location": "L1"}]
    path.write_text(json.dumps({"nodes": nodes, "links": []}), encoding="utf-8")


def test_a_graph_is_parsed_once_until_it_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph_module.clear_graph_cache()
    path = tmp_path / "graph.json"
    _graph(path, "login()")
    calls = []
    real = graph_module.load_graph
    monkeypatch.setattr(graph_module, "load_graph", lambda p, **k: calls.append(p) or real(p, **k))
    first = graph_module.load_graph_cached(path)
    second = graph_module.load_graph_cached(path)
    assert first is second and len(calls) == 1
    time.sleep(0.05)
    _graph(path, "logout_everywhere()")  # a rebuild: new size and mtime
    third = graph_module.load_graph_cached(path)
    assert (
        len(calls) == 2
        and third is not None
        and "logout_everywhere()" in {n.label for n in third.nodes.values()}
    )


def test_the_cache_is_bounded(tmp_path: Path) -> None:
    graph_module.clear_graph_cache()
    for i in range(graph_module.GRAPH_CACHE_SIZE + 3):
        path = tmp_path / f"g{i}.json"
        _graph(path, f"f{i}()")
        graph_module.load_graph_cached(path)
    assert graph_module.cached_graphs() == graph_module.GRAPH_CACHE_SIZE


def test_a_missing_graph_is_not_cached(tmp_path: Path) -> None:
    graph_module.clear_graph_cache()
    assert graph_module.load_graph_cached(tmp_path / "none.json") is None
    assert graph_module.cached_graphs() == 0


def test_a_repeated_query_runs_no_git_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Agents fire queries in bursts: once warm, a query costs no subprocess (HEAD from the git
    memo; the deep index's staleness verdict reused for a few seconds)."""
    from cairn import providers
    from cairn.bench.workspace import materialize
    from cairn.discover import proc
    from cairn.emit import write_outputs
    from cairn.mcp_server import tools
    from cairn.providers.graphify import GraphifyProvider
    from cairn.scan import scan_workspace
    from tests.test_graphify_provider import _fake_graphify

    src = tmp_path / "src" / "app"
    src.mkdir(parents=True)
    (src / ".fixture-repo").write_text("", encoding="utf-8")
    (src / "auth.py").write_text("def login():\n    return True\n", encoding="utf-8")
    ws = materialize(tmp_path / "src", tmp_path / "ws").resolve()
    write_outputs(ws, scan_workspace(ws))
    fake = GraphifyProvider(executable=_fake_graphify(tmp_path))
    monkeypatch.setattr(providers, "default_provider", lambda: fake)
    fake.build(ws, "app", ws / "app", timeout=60)
    first = tools.query_text(ws, "app", "login")
    calls = []
    for name in ("run_text", "run_bytes", "run_text_tree"):
        real = getattr(proc, name)

        def counting(*a, _real=real, **k):  # type: ignore[no-untyped-def]
            calls.append(a[0][:3] if a else None)
            return _real(*a, **k)

        monkeypatch.setattr(proc, name, counting)
        for module in ("cairn.discover.git", "cairn.scan_cache", "cairn.providers.graphify"):
            mod = __import__(module, fromlist=["x"])
            if hasattr(mod, name):
                monkeypatch.setattr(mod, name, counting)
    assert tools.query_text(ws, "app", "login") == first
    assert calls == []


def test_an_edit_is_flagged_once_the_staleness_verdict_lapses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cairn import providers
    from cairn.bench.workspace import materialize
    from cairn.emit import write_outputs
    from cairn.mcp_server import tools
    from cairn.providers.graphify import GraphifyProvider
    from cairn.scan import scan_workspace
    from tests.test_graphify_provider import _fake_graphify

    src = tmp_path / "src" / "app"
    src.mkdir(parents=True)
    (src / ".fixture-repo").write_text("", encoding="utf-8")
    (src / "auth.py").write_text("def login():\n    return True\n", encoding="utf-8")
    ws = materialize(tmp_path / "src", tmp_path / "ws").resolve()
    write_outputs(ws, scan_workspace(ws))
    fake = GraphifyProvider(executable=_fake_graphify(tmp_path))
    monkeypatch.setattr(providers, "default_provider", lambda: fake)
    fake.build(ws, "app", ws / "app", timeout=60)
    assert "may be stale" not in tools.query_text(ws, "app", "login")
    (ws / "app" / "auth.py").write_text("def login():\n    return 9\n", encoding="utf-8")
    monkeypatch.setattr(tools, "STALE_TTL", 0.0)
    assert "may be stale" in tools.query_text(ws, "app", "login")


def _ranked_by_scoring_every_node(graph: graph_module.Graph, question: str, limit: int) -> list:
    words = graph_module._query_tokens(question)
    memo: dict = {}
    scored = []
    for node in graph.nodes.values():
        score = graph_module._score(node, words, memo)
        if score >= graph_module._MIN_SCORE:
            scored.append((-score, -graph.degree(node.id), node.label, node.id))
    scored.sort()
    return [graph_module._hit(graph, graph.nodes[i]) for *_, i in scored[:limit]]


def _vocabulary_graph(tmp_path: Path) -> graph_module.Graph:
    labels = [
        "getUserById()",
        "UserService",
        "login()",
        "loginHandler()",
        "authenticate()",
        "authentication.py",
        "PaymentWebhook",
        "verifySignature()",
        "signatures",
        "OrderSummary",
        "renderOrder()",
        "connectionPool",
        "ConfigParser",
        "parseConfig()",
        "configuration",
        "HTTPServer",
        "users",
        "userlogin",
        "summarise()",
        "databases",
    ]
    nodes = [
        {
            "id": f"n{i}",
            "label": label,
            "source_file": f"src/f{i % 7}.py",
            "source_location": f"L{i + 1}",
        }
        for i, label in enumerate(labels)
    ]
    links = [{"source": f"n{i}", "target": f"n{(i * 3 + 1) % len(labels)}"} for i in range(20)]
    path = tmp_path / "graph.json"
    path.write_text(json.dumps({"nodes": nodes, "links": links}), encoding="utf-8")
    graph = graph_module.load_graph(path)
    assert graph is not None
    return graph


@pytest.mark.parametrize(
    "question",
    [
        "where is user login handled",
        "userlogin",
        "verify payment webhook signature",
        "render the order summary",
        "database connection pool",
        "parse configuration",
        "authenticate users",
        "http server",
        "nothing matches here",
    ],
)
def test_ranking_only_candidates_matches_scoring_every_node(tmp_path: Path, question: str) -> None:
    graph = _vocabulary_graph(tmp_path)
    assert graph_module.rank(graph, question, 5) == _ranked_by_scoring_every_node(
        graph, question, 5
    )


def test_a_repeated_question_compares_no_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph = _vocabulary_graph(tmp_path)
    first = graph_module.rank(graph, "verify payment signature", 5)
    calls = []
    real = graph_module._similarity
    monkeypatch.setattr(
        graph_module, "_similarity", lambda a, b: calls.append((a, b)) or real(a, b)
    )
    assert graph_module.rank(graph, "verify payment signature", 5) == first
    assert calls == []
