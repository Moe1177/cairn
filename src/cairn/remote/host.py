"""What cairn asks of a code host, and the shapes the answers come in. GitHub's and GitLab's APIs
answer the same questions, and so does git itself for a list of repos on any other host (all
but code search), so the org features work over each.

A repo's name is its full path on the host: owner/name on GitHub, and on GitLab the group and any
subgroups too (`acme/platform/api`).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CodeHit:
    repo: str  # full path, owner/name on GitHub
    path: str
    fragments: tuple[str, ...] = ()


@dataclass(frozen=True)
class SearchPage:
    hits: tuple[CodeHit, ...]
    total: int
    ms: float  # time spent on the request itself
    waited: float = 0.0  # seconds spent waiting out rate limits first


@dataclass(frozen=True)
class RepoInfo:
    name: str  # full path, owner/name on GitHub
    default_branch: str
    language: str = ""
    topics: tuple[str, ...] = ()
    archived: bool = False
    fork: bool = False
    # ISO time of the last push (GitLab: of the last activity; plain git: the tip commit's id,
    # only ever compared for a change)
    pushed: str = ""
    description: str = ""


class CodeHost(Protocol):
    """A read-only client for one host. Queries use GitHub's search syntax: words, then an
    `org:` qualifier naming the org (on GitLab, the group) to search in."""

    def search_code(self, query: str, *, per_page: int = 10) -> SearchPage: ...

    def search_repos(self, query: str, *, per_page: int = 10) -> tuple[tuple[str, ...], float]: ...

    def file_exists(self, repo: str, path: str) -> bool: ...

    def read_file(self, repo: str, path: str, *, max_bytes: int = 200_000) -> str | None: ...

    def list_repos(
        self, owner: str, *, page: int = 1, per_page: int = 100
    ) -> tuple[RepoInfo, ...]: ...

    def tree(self, repo: str, ref: str) -> tuple[tuple[str, ...], bool]: ...

    def prefetch(self, repo: str, paths: Sequence[str]) -> None:
        """Get ready to read these files of `repo` (plain git fetches them in one request)."""

    def remaining(self, resource: str = "core") -> int | None: ...


def in_org(repo: str, org: str) -> bool:
    """Whether `repo` (a full path) belongs to `org`, a GitLab group's subgroups included."""
    return repo.lower().startswith(f"{org.lower()}/")
