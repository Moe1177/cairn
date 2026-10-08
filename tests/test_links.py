"""Spec §28: which repos a repo is linked to, with direction, in the terminal and for agents."""

import json
from pathlib import Path

import pytest
from mcp import Client
from typer.testing import CliRunner

from cairn.cli import app
from cairn.integrations import harnesses as h
from cairn.integrations.claude import install_claude
from cairn.integrations.homes import claude_home
from cairn.mcp_server import tools
from cairn.mcp_server.server import build_server
from cairn.model.graph import Confidence, Edge, EdgeType, Evidence, Repo, Workspace
from cairn.render.links import (
    BOTH_WAYS,
    ONE_WAY_IN,
    ONE_WAY_OUT,
    hidden_count,
    links_json,
    neighbors,
    render_links,
    repo_at,
)
from tests.helpers import make_repo

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "workspaces" / "cloudshop"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _edge(source: str, target: str, type_: EdgeType, *signals: str, sure: bool = True) -> Edge:
    return Edge(
        source=source,
        target=target,
        type=type_,
        confidence=Confidence.INFERRED if sure else Confidence.AMBIGUOUS,
        score=0.6 if sure else 0.2,
        signals=signals,
        evidence=(Evidence(repo=source, file="f.txt", line=1, snippet="x"),),
    )


def _map(*edges: Edge) -> Workspace:
    ids = sorted({e.source for e in edges} | {e.target for e in edges} | {"api"})
    return Workspace(
        workspace_root="/ws",
        generated_at="now",
        repos=tuple(Repo(id=i, path=i) for i in ids),
        edges=edges,
    )


# --- the summary --------------------------------------------------------------------------------


def test_each_linked_repo_gets_one_line_with_its_direction() -> None:
    workspace = _map(
        _edge("api", "billing", EdgeType.CALLS_HTTP, "http_route:/charge", "http_route:/refund"),
        _edge("web", "api", EdgeType.CALLS_HTTP, "http_route:/trips/:id"),
        _edge("api", "worker", EdgeType.PUBSUB, "topic:trip.completed"),
        _edge("worker", "api", EdgeType.USES_RESOURCE, "resource:sqs:jobs"),
        _edge("api", "reports", EdgeType.SHARES_DB, "db_table:trips", "db_table:drivers"),
    )
    found = {n.repo: n for n in neighbors(workspace, "api")}
    assert found["billing"].direction == ONE_WAY_OUT
    assert found["billing"].phrases == ("calls it (2 routes)",)
    assert found["web"].direction == ONE_WAY_IN
    assert found["web"].phrases == ("calls this repo (1 route)",)
    assert found["worker"].direction == BOTH_WAYS
    assert found["worker"].phrases == (
        "sends it events (trip.completed)",
        "uses this repo's SQS queue jobs",
    )
    assert found["reports"].direction == BOTH_WAYS  # a shared database goes both ways
    assert found["reports"].phrases == ("shares 2 tables",)


def test_the_text_has_a_count_aligned_columns_and_reads_from_this_repo() -> None:
    workspace = _map(
        _edge("api", "billing-service", EdgeType.DEPENDS_ON_PACKAGE, "package:@acme/billing"),
        _edge("web", "api", EdgeType.MENTIONS, "doc_mention"),
        _edge("api", "web", EdgeType.MENTIONS, "doc_mention"),
    )
    text = render_links("api", neighbors(workspace, "api"))
    lines = text.splitlines()
    assert lines[0] == "api is linked to 2 repos:"
    assert lines[1] == "  billing-service  → one way    uses its package @acme/billing"
    assert lines[2] == "  web              ↔ both ways  mentions each other in docs"
    one = render_links("api", neighbors(_map(_edge("api", "web", EdgeType.DEPLOYS)), "api"))
    assert one.splitlines()[0] == "api is linked to 1 repo:"


def test_unconfirmed_links_are_counted_and_shown_only_on_request() -> None:
    workspace = _map(
        _edge("api", "web", EdgeType.CALLS_HTTP, "http_route:/x"),
        _edge("api", "old-api", EdgeType.MIRRORS, "package:api", sure=False),
    )
    text = render_links("api", neighbors(workspace, "api"), hidden=hidden_count(workspace, "api"))
    assert "old-api" not in text
    assert "1 more repo is linked only by unconfirmed links; include them with --all." in text
    every = render_links("api", neighbors(workspace, "api", include_unconfirmed=True))
    assert "old-api  ↔ both ways  copy of the same app (unconfirmed)" in every


def test_a_repo_without_links_says_so() -> None:
    assert render_links("api", ()) == "api is not linked to any other repo in this map."


def test_json_keeps_direction_summary_and_evidence() -> None:
    workspace = _map(_edge("api", "billing", EdgeType.CALLS_HTTP, "http_route:/charge"))
    data = links_json("api", neighbors(workspace, "api"))
    (link,) = data["links"]
    assert data["repo"] == "api" and link["repo"] == "billing" and link["direction"] == "out"
    assert link["summary"] == ["calls it (1 route)"]
    assert link["edges"][0]["evidence"] == ["api/f.txt:1"]


def test_the_repo_you_are_in_is_the_deepest_one_containing_the_folder(tmp_path: Path) -> None:
    workspace = Workspace(
        workspace_root=str(tmp_path),
        generated_at="now",
        repos=(Repo(id="outer", path="outer"), Repo(id="inner", path="outer/vendor/inner")),
    )
    (tmp_path / "outer" / "vendor" / "inner" / "src").mkdir(parents=True)
    found = repo_at(workspace, tmp_path, tmp_path / "outer" / "vendor" / "inner" / "src")
    assert found is not None and found.id == "inner"
    found = repo_at(workspace, tmp_path, tmp_path / "outer")
    assert found is not None and found.id == "outer"
    assert repo_at(workspace, tmp_path, tmp_path) is None


# --- `cairn links` and the `links` MCP tool, on a real map ---------------------------------------


@pytest.fixture
def cloudshop(materialize) -> Path:
    ws = materialize("cloudshop").resolve()
    tools.rescan(ws)
    return ws


def test_cairn_links_lists_the_repo_you_are_in(cloudshop: Path, monkeypatch) -> None:
    monkeypatch.chdir(cloudshop / "shipping-service")
    result = CliRunner().invoke(app, ["links"])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0] == "shipping-service is linked to 2 repos:"
    assert lines[1].startswith("  orders-service    ↔ both ways  uses its DynamoDB table orders")
    assert lines[2].startswith(
        "  payments-service  ↔ both ways  uses its SQS queue payment-requests"
    )


def test_cairn_links_by_name_with_evidence_and_json(cloudshop: Path, monkeypatch) -> None:
    monkeypatch.chdir(cloudshop)
    result = CliRunner().invoke(app, ["links", "platform-infra", "--evidence"])
    assert "platform-infra is linked to 2 repos:" in result.output
    assert "← one way" in result.output and "orders-service/serverless.yml" in result.output
    data = json.loads(CliRunner().invoke(app, ["links", "orders-service", "--json"]).output)
    assert {link["repo"] for link in data["links"]} >= {"platform-infra", "shipping-service"}


def test_cairn_links_outside_a_repo_or_a_map_says_what_to_do(
    cloudshop: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(cloudshop)
    result = CliRunner().invoke(app, ["links"])
    assert result.exit_code == 1 and "Name one: `cairn links <repo>`" in result.output
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["links"])
    assert result.exit_code == 1 and "No cairn map here" in result.output


@pytest.mark.anyio
async def test_the_links_tool_answers_for_the_repo_the_session_is_in(cloudshop: Path) -> None:
    server = build_server(cloudshop, start=cloudshop / "payments-service" / "infra")
    async with Client(server) as client:
        tool = next(t for t in (await client.list_tools()).tools if t.name == "links")
        assert "show this list to them as is" in (tool.description or "")
        here = await client.call_tool("links", {})
        assert here.content[0].text.startswith("payments-service is linked to")
        named = await client.call_tool("links", {"repo": "platform-infra"})
        assert named.content[0].text.startswith("platform-infra is linked to 2 repos:")
    outside = build_server(cloudshop, start=cloudshop)
    async with Client(outside) as client:
        result = await client.call_tool("links", {})
        assert "name one" in result.content[0].text


# --- `cairn uninstall claude` says what it removed -----------------------------------------------


def test_uninstall_reports_exactly_what_it_removed(tmp_path: Path, monkeypatch) -> None:
    ws = tmp_path / "ws"
    make_repo(ws, "alpha", {"README.md": "# a\n"})
    tools.rescan(ws)
    monkeypatch.setattr(h, "_claude_cli", lambda args: (0, "Removed MCP server cairn"))
    skill = claude_home() / "skills" / "cairn" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text("x", encoding="utf-8")
    (line,) = h.uninstall_harness("claude", ws)
    assert line == "Claude Code: removed the /cairn skill, the cairn MCP server."
    install_claude(ws)
    monkeypatch.setattr(h, "_claude_cli", lambda args: (1, "No MCP server named cairn"))
    (line,) = h.uninstall_harness("claude", ws)
    assert line == "Claude Code: removed the index block in CLAUDE.md."
    (line,) = h.uninstall_harness("claude", ws)
    assert line == "Claude Code: nothing to remove (no index block, skill or MCP server)."


def test_a_console_that_cannot_show_arrows_gets_ascii_ones(monkeypatch) -> None:
    from cairn import cli

    class Legacy:
        encoding = "cp1252"

    monkeypatch.setattr(cli.sys, "stdout", Legacy())
    assert cli._printable("  web  ↔ both ways  …") == "  web  <-> both ways  ..."
    monkeypatch.setattr(cli.sys, "stdout", type("Utf8", (), {"encoding": "utf-8"})())
    assert cli._printable("→ one way") == "→ one way"
