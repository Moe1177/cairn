from pathlib import Path

import pytest
from mcp import Client

from cairn.mcp_server import tools
from cairn.mcp_server.server import build_server, find_workspace


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_find_workspace_walks_up(materialize, tmp_path: Path, monkeypatch) -> None:
    # Review Focus 2
    monkeypatch.setenv("CAIRN_HOME", str(tmp_path / "ch"))
    ws = materialize("mini-eats").resolve()
    tools.rescan(ws)
    assert find_workspace(ws / "eats-admin" / "eats-admin" / "lib") == ws
    assert find_workspace(tmp_path) is None


@pytest.mark.anyio
async def test_server_exposes_six_tools(materialize) -> None:
    ws = materialize("mini-eats").resolve()
    tools.rescan(ws)
    server = build_server(ws)
    assert ".cairn/INDEX.md" in (server.instructions or "")
    async with Client(server) as client:
        names = sorted(t.name for t in (await client.list_tools()).tools)
        assert names == ["find_across", "query", "refresh", "related", "repo_card", "resolve_repo"]
        result = await client.call_tool("resolve_repo", {"name_or_alias": "owner portal"})
        assert result.content[0].text.startswith("- eats-admin")
