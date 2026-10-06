"""Phase 3 final-review fixes (spec §23): timeouts, staleness, recall, big graphs, cmd shims."""

import json
import os
import time
from pathlib import Path

import pytest

from cairn.providers import graph as graph_module
from cairn.providers.graph import load_graph, rank
from cairn.providers.graphify import GraphifyProvider
from tests.test_graphify_provider import _fake_graphify, _workspace


def test_timeout_kills_the_whole_process_tree(tmp_path: Path) -> None:
    ws, repo = _workspace(tmp_path)
    slow = GraphifyProvider(
        executable=_fake_graphify(tmp_path), extra_env={"FAKE_CHILD": "1", "FAKE_SLEEP": "30"}
    )
    started = time.monotonic()
    result = slow.build(ws, "app", repo, timeout=2)
    assert not result.ok and "timed out" in result.message
    assert time.monotonic() - started < 15


def test_an_edit_during_the_build_leaves_the_index_stale(tmp_path: Path) -> None:
    ws, repo = _workspace(tmp_path)
    provider = GraphifyProvider(
        executable=_fake_graphify(tmp_path), extra_env={"FAKE_TOUCH": str(repo / "auth.py")}
    )
    assert provider.build(ws, "app", repo, timeout=60).ok
    assert provider.status(ws, "app", repo).stale


def test_an_oversized_graph_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws, repo = _workspace(tmp_path)
    monkeypatch.setattr(graph_module, "MAX_GRAPH_BYTES", 10)
    result = GraphifyProvider(executable=_fake_graphify(tmp_path)).build(
        ws, "app", repo, timeout=60
    )
    assert not result.ok and "too large" in result.message and "next" not in result.message


def test_graphify_next_hints_are_never_relayed(tmp_path: Path) -> None:
    ws, repo = _workspace(tmp_path)
    failing = GraphifyProvider(executable=_fake_graphify(tmp_path), extra_env={"FAKE_FAIL": "1"})
    result = failing.build(ws, "app", repo, timeout=60)
    assert not result.ok and "boom" in result.message and "cluster-only" not in result.message


@pytest.mark.skipif(os.name != "nt", reason="cmd.exe metacharacters only matter on Windows")
def test_a_cmd_shim_refuses_paths_cmd_would_interpret(tmp_path: Path) -> None:
    ws, repo = _workspace(tmp_path)
    odd = ws / "a&b"
    repo.rename(odd)
    result = GraphifyProvider(executable=_fake_graphify(tmp_path)).build(ws, "app", odd, timeout=60)
    assert not result.ok and ".cmd" in result.message
    assert not (ws / ".cairn" / "deep" / "app" / "graphify-out" / "record.json").exists()


def _ranked(tmp_path: Path, labels: list[str], question: str) -> list[str]:
    nodes = [
        {"id": str(i), "label": label, "source_file": "src/a.ts", "source_location": f"L{i + 1}"}
        for i, label in enumerate(labels)
    ]
    path = tmp_path / "graph.json"
    path.write_text(json.dumps({"nodes": nodes, "links": []}), encoding="utf-8")
    graph = load_graph(path)
    assert graph is not None
    return [hit.label for hit in rank(graph, question, 3)]


LABELS = [
    "createSession()",
    "SessionManager",
    "validateToken()",
    "handleLogin()",
    "getUserById()",
    "UserSessionManager",
]


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("where is the session created?", "createSession()"),
        ("token validation", "validateToken()"),
        ("where is login handled", "handleLogin()"),
        ("get user by id", "getUserById()"),
    ],
)
def test_camel_and_pascal_case_symbols_are_found(
    tmp_path: Path, question: str, expected: str
) -> None:
    assert _ranked(tmp_path, LABELS, question)[:1] == [expected]
