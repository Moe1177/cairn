"""Which org a call means, and one API client per host for the life of the process (its
keep-alive connections are what make a session's later calls fast).

The configured orgs are a boundary: an agent's call names one of them or none, never another
org or another owner's repo, so text it read somewhere can't steer cairn to other private code
the token can see, or send an Enterprise org's words to github.com. On GitLab a group's
subgroups are inside it: `platform/api` there is the org's `acme/platform/api`.
"""

import threading
from collections.abc import Callable, Sequence
from typing import TypeVar

from cairn.config import OrgSource
from cairn.errors import CairnError
from cairn.remote.auth import github_token, gitlab_token
from cairn.remote.github import GitHub
from cairn.remote.gitlab import GitLab
from cairn.remote.host import CodeHost

_CLIENTS: dict[tuple[str, str], CodeHost] = {}  # (kind, host) -> its client
T = TypeVar("T")
_LOCK = threading.Lock()

NO_ORGS = (
    "no org configured: add it to .cairn/config.yaml, e.g.\n"
    "orgs:\n  - org: acme            # host: github.com by default (Enterprise: host: git.acme.com)\n"
    "  - org: acme/platform   # a GitLab group: host: gitlab.com (self-managed: add kind: gitlab)"
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
    """The full path of a repo of `source`: its name, or its path with the org in front. On
    GitLab a path without the org is one inside it (a subgroup's repo)."""
    name = repo.strip().strip("/")
    prefix = f"{source.org.lower()}/"
    if name.lower().startswith(prefix):
        name = name[len(prefix) :]
    elif "/" in name and source.kind == "github":
        raise CairnError(f"{repo.strip()!r} isn't in {source.org}: read only the org's own repos")
    return f"{source.org}/{name}"


def client_for(source: OrgSource) -> CodeHost:
    key = (source.kind, source.host)
    with _LOCK:
        client = _CLIENTS.get(key)
        if client is None:
            client = (
                GitLab(gitlab_token(source.host), host=source.host)
                if source.kind == "gitlab"
                else GitHub(github_token(source.host), host=source.host)
            )
            _CLIENTS[key] = client
        return client


def with_client(source: OrgSource, call: Callable[[CodeHost], T]) -> T:
    """`call` with the host's client; a rejected token is dropped, so a new login works."""
    try:
        return call(client_for(source))
    except CairnError as exc:
        if "rejected the token" in str(exc):
            forget_client(source)
        raise


def forget_client(source: OrgSource) -> None:
    """Drop the host's client (after the host rejected its token): the next call reads the
    token again, so a fresh `gh auth login` or `glab auth login` works without a restart."""
    with _LOCK:
        _CLIENTS.pop((source.kind, source.host), None)
