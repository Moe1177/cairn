"""cairn's MCP server: one stdio process per harness session, workspace found from cwd."""

from collections.abc import Callable
from pathlib import Path

from mcp.server import MCPServer

from cairn import __version__
from cairn.errors import CairnError
from cairn.integrations.content import pointer_text
from cairn.integrations.registry import find_workspace  # re-exported: older imports
from cairn.mcp_server import tools


def _safe(call: Callable[[], str]) -> str:
    """Tool errors come back as readable text, never as an opaque tool failure."""
    try:
        return call()
    except CairnError as exc:
        return f"cairn error: {exc}"
    except (OSError, ValueError) as exc:
        return f"cairn error: {type(exc).__name__}: {exc}"


def _missing(start: Path) -> str:
    return (
        f"No cairn workspace found at or above {start.as_posix()}. Run `cairn init` in the folder "
        "that contains your repos (or ask Claude to run the /cairn skill); these tools pick the "
        "map up as soon as it exists."
    )


def build_server(ws_root: Path | None, *, start: Path | None = None) -> MCPServer:
    """Serve `ws_root`, or, outside a workspace, look for one again on every call: a server
    started in every project (or by a plugin) works as soon as `cairn init` maps the folder."""
    origin = start or Path.cwd()

    def root() -> Path | None:
        return ws_root if ws_root is not None else find_workspace(origin)

    def answer(call: Callable[[Path], str]) -> str:
        found = root()
        return _missing(origin) if found is None else _safe(lambda: call(found))

    instructions = pointer_text([ws_root.as_posix()]) if ws_root else _missing(origin)
    server = MCPServer("cairn", instructions=instructions, version=__version__)

    @server.tool()
    def resolve_repo(name_or_alias: str) -> str:
        """Find which workspace repo a name, alias, or description means (e.g. 'the admin dashboard')."""
        return answer(lambda ws: tools.resolve_text(ws, name_or_alias))

    @server.tool()
    def repo_card(repo: str) -> str:
        """Short card for a repo: purpose, run commands, layout, relationships. Read before exploring it."""
        return answer(lambda ws: tools.card_text(ws, repo))

    @server.tool()
    def links(repo: str = "", include_unconfirmed: bool = False) -> str:
        """Which repos a repo is linked to, one line each: "→ one way" (it uses that repo), "← one way" (that repo uses it) or "↔ both ways", and what connects them. Leave repo empty for the repo this session is in. When the user asks what a repo links to, show this list to them as is; call related for the evidence."""
        return answer(lambda ws: tools.links_text(ws, repo, origin, include_unconfirmed))

    @server.tool()
    def related(repo: str, edge_type: str | None = None, include_unconfirmed: bool = False) -> str:
        """Repos related to `repo`, with evidence. edge_type: calls_http, grpc, pubsub, uses_resource, compose_link, deploys, mirrors, shares_db, depends_on_package, path_ref, shares_env, mentions, manual."""
        return answer(lambda ws: tools.related_text(ws, repo, edge_type, include_unconfirmed))

    @server.tool()
    def find_across(query: str, kind: str | None = None) -> str:
        """Which repos expose or consume something: a route, table, topic, gRPC service, AWS resource (sqs:orders), package, or path. kind: http_route, db_table, topic, grpc_service, cloud_resource, platform_service, package, env_var_name, path_ref."""
        return answer(lambda ws: tools.find_across_text(ws, query, kind))

    @server.tool()
    def query(repo: str, question: str) -> str:
        """Where in the code is X? file:line hits in this repo, repos the question names, and
        related repos unless a literal answered; grep first, a deep index's symbols when built."""
        return answer(lambda ws: tools.query_text(ws, repo, question))

    @server.tool()
    def refresh() -> str:
        """Re-scan the workspace after repos changed."""
        return answer(tools.refresh_text)

    return server
