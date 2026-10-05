"""cairn's MCP server: one stdio process per harness session, workspace found from cwd."""

from collections.abc import Callable
from pathlib import Path

from mcp.server import MCPServer

from cairn.errors import CairnError
from cairn.integrations.content import pointer_text
from cairn.integrations.registry import list_workspaces
from cairn.mcp_server import tools
from cairn.paths import workspace_file


def find_workspace(start: Path) -> Path | None:
    """Nearest folder at or above `start` with a cairn map, else a registered ancestor."""
    start = start.resolve()
    for folder in (start, *start.parents):
        if workspace_file(folder).is_file():
            return folder
    for entry in list_workspaces():
        root = Path(entry)
        if root == start or root in start.parents:
            return root
    return None


def _safe(call: Callable[[], str]) -> str:
    try:
        return call()
    except CairnError as exc:
        return f"cairn error: {exc}"


def build_server(ws_root: Path) -> MCPServer:
    server = MCPServer("cairn", instructions=pointer_text([ws_root.as_posix()]))

    @server.tool()
    def resolve_repo(name_or_alias: str) -> str:
        """Find which workspace repo a name, alias, or description means (e.g. 'the admin dashboard')."""
        return _safe(lambda: tools.resolve_text(ws_root, name_or_alias))

    @server.tool()
    def repo_card(repo: str) -> str:
        """Short card for a repo: purpose, run commands, layout, relationships. Read before exploring it."""
        return _safe(lambda: tools.card_text(ws_root, repo))

    @server.tool()
    def related(repo: str, edge_type: str | None = None, include_unconfirmed: bool = False) -> str:
        """Repos related to `repo`, with evidence. edge_type: shares_db, depends_on_package, path_ref, mentions, manual."""
        return _safe(lambda: tools.related_text(ws_root, repo, edge_type, include_unconfirmed))

    @server.tool()
    def find_across(query: str, kind: str | None = None) -> str:
        """Which repos expose or consume something: a table, package, or path. kind: db_table, package, path_ref."""
        return _safe(lambda: tools.find_across_text(ws_root, query, kind))

    @server.tool()
    def query(repo: str, question: str) -> str:
        """Ask a code-level question about one repo (deep index when available, else where to look)."""
        return _safe(lambda: tools.query_text(ws_root, repo, question))

    @server.tool()
    def refresh() -> str:
        """Re-scan the workspace after repos changed."""
        return _safe(lambda: tools.refresh_text(ws_root))

    return server
