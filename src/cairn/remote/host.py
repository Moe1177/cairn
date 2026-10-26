"""What cairn asks of a code host's API, and the shapes the answers come in. GitHub and GitLab
answer the same questions, so the org features work over either.

A repo's name is its full path on the host: owner/name on GitHub, and on GitLab the group and any
subgroups too (`acme/platform/api`).
"""

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
    pushed: str = ""  # ISO time of the last push (GitLab: of the last activity)
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

    def remaining(self, resource: str = "core") -> int | None: ...


def in_org(repo: str, org: str) -> bool:
    """Whether `repo` (a full path) belongs to `org`, a GitLab group's subgroups included."""
    return repo.lower().startswith(f"{org.lower()}/")
