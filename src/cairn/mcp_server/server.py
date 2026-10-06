"""cairn's MCP server: one stdio process per harness session, workspace found from cwd."""

from collections.abc import Callable
from pathlib import Path

from mcp.server import MCPServer

from cairn import __version__
from cairn.errors import CairnError
from cairn.integrations.content import pointer_text
from cairn.integrations.registry import list_workspaces
from cairn.mcp_server import tools
from cairn.paths import workspace_file


def find_workspace(start: Path) -> Path | None:
    """Nearest folder at or above `start` with a cairn map, else a registered ancestor."""
    start = start.resolve()
    for folder in (start, *start.parents):
        if workspace_file(folder).is_file() and not _inside_git_repo(folder):
            return folder
    for entry in list_workspaces():
        root = Path(entry)
        if root == start or root in start.parents:
            return root
    return None


def _inside_git_repo(folder: Path) -> bool:
    """A workspace contains repos; a `.cairn/` inside a repo was committed there, so its map
    (repo ids, paths) is untrusted input and is never served (spec §20.1)."""
    return any((p / ".git").exists() for p in (folder, *folder.parents))


def _safe(call: Callable[[], str]) -> str:
    """Tool errors come back as readable text, never as an opaque tool failure."""
    try:
        return call()
    except CairnError as exc:
        return f"cairn error: {exc}"
    except (OSError, ValueError) as exc:
        return f"cairn error: {type(exc).__name__}: {exc}"


def _no_workspace_server(start: Path) -> MCPServer:
    """Globally registered servers start in every project; outside a workspace, explain instead of failing."""
    message = (
        f"No cairn workspace found at or above {start.as_posix()}. Run `cairn init` in the folder "
        "that contains your repos, then restart this session."
    )
    server = MCPServer("cairn", instructions=message, version=__version__)

    def resolve_repo(name_or_alias: str) -> str:
        return message

    def repo_card(repo: str) -> str:
        return message

    def related(repo: str, edge_type: str | None = None, include_unconfirmed: bool = False) -> str:
        return message

    def find_across(query: str, kind: str | None = None) -> str:
        return message

    def query(repo: str, question: str) -> str:
        return message

    def refresh() -> str:
        return message

    for stub in (resolve_repo, repo_card, related, find_across, query, refresh):
        server.add_tool(stub, description=message)
    return server


def build_server(ws_root: Path | None, *, start: Path | None = None) -> MCPServer:
    if ws_root is None:
        return _no_workspace_server(start or Path.cwd())
    server = MCPServer(
        "cairn", instructions=pointer_text([ws_root.as_posix()]), version=__version__
    )

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
        """Repos related to `repo`, with evidence. edge_type: calls_http, grpc, pubsub, compose_link, shares_db, depends_on_package, path_ref, shares_env, mentions, manual."""
        return _safe(lambda: tools.related_text(ws_root, repo, edge_type, include_unconfirmed))

    @server.tool()
    def find_across(query: str, kind: str | None = None) -> str:
        """Which repos expose or consume something: a route, table, topic, gRPC service, package, or path. kind: http_route, db_table, topic, grpc_service, package, env_var_name, path_ref."""
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
