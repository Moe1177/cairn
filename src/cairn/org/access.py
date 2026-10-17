"""Which org a call means, and one API client per host for the life of the process (its
keep-alive connections are what make a session's later calls fast).

The configured orgs are a boundary: an agent's call names one of them or none, never another
org or another owner's repo, so text it read somewhere can't steer cairn to other private code
the token can see, or send an Enterprise org's words to github.com.
"""

import threading
from collections.abc import Sequence

from cairn.config import OrgSource
from cairn.errors import CairnError
from cairn.remote.auth import github_token
from cairn.remote.github import GitHub

_CLIENTS: dict[str, GitHub] = {}
_LOCK = threading.Lock()

NO_ORGS = (
    "no org configured: add it to .cairn/config.yaml, e.g.\n"
    "orgs:\n  - org: acme            # host: github.com by default (Enterprise: host: git.acme.com)"
)


def pick_org(orgs: Sequence[OrgSource], name: str = "") -> OrgSource:
    """The configured org called `name`, or the only one when `name` is empty."""
    if not orgs:
        raise CairnError(NO_ORGS)
    names = ", ".join(source.org for source in orgs)
    if name.strip():
        for source in orgs:
            if source.org.lower() == name.strip().lower():
                return source
        raise CairnError(f"{name.strip()!r} isn't a configured org (configured: {names})")
    if len(orgs) > 1:
        raise CairnError(f"several orgs are configured ({names}): say which one")
    return orgs[0]


def org_repo(source: OrgSource, repo: str) -> str:
    """owner/name for a repo of `source`: its name, or owner/name with the org as the owner."""
    owner, _, name = repo.strip().rpartition("/")
    if owner and owner.lower() != source.org.lower():
        raise CairnError(f"{repo.strip()!r} isn't in {source.org}: read only the org's own repos")
    return f"{source.org}/{name}"


def client_for(source: OrgSource) -> GitHub:
    with _LOCK:
        client = _CLIENTS.get(source.host)
        if client is None:
            client = GitHub(github_token(source.host), host=source.host)
            _CLIENTS[source.host] = client
        return client


def forget_client(source: OrgSource) -> None:
    """Drop the host's client (after GitHub rejected its token): the next call reads the token
    again, so a fresh `gh auth login` works without restarting the MCP server."""
    with _LOCK:
        _CLIENTS.pop(source.host, None)
