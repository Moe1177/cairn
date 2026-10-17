"""User configuration (.cairn/config.yaml). Every field has a safe default."""

import re
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from cairn.model.graph import Frozen
from cairn.remote.giturl import is_repo_path, repo_url

_ORG = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
# A GitLab group, with any subgroups (acme/platform): segments as GitLab allows them.
_GROUP = re.compile(
    r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,254}(?:/[A-Za-z0-9_][A-Za-z0-9_.-]{0,254}){0,19}$"
)
_HOST = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?(?:\.[A-Za-z0-9-]{1,63})+$")


class OrgSource(Frozen):
    """An org (or user) on a code host whose repos cairn reads over the API, never cloning. On
    GitLab, the org is a group, a subgroup (acme/platform) or a user. On any other git host it
    is a list of repo URLs under one path (kind git): cairn keeps a clone of each with no file
    contents, only its latest tree, and fetches the few files it reads."""

    org: str
    host: str = "github.com"
    # Which API the host speaks: gitlab for gitlab.com and gitlab.* hosts unless said otherwise,
    # git (none: plain git) when the org lists its repos.
    kind: Literal["github", "gitlab", "git"] = "github"
    repos: tuple[str, ...] = ()  # kind git: its repos' URLs (https, or ssh as git@host:path)

    @model_validator(mode="before")
    @classmethod
    def _infer_kind(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        listed = isinstance(data.get("repos"), list | tuple)  # else pydantic says it's no list
        if listed and data["repos"] and not data.get("host"):  # the URLs name it
            found = repo_url(str(data["repos"][0]))
            data = {**data, "host": found[0]} if found else data
        if not data.get("kind"):
            host = str(data.get("host") or "github.com").lower()
            gitlab = host == "gitlab.com" or host.startswith("gitlab.")
            kind = "git" if listed else "gitlab" if gitlab else "github"
            return {**data, "kind": kind}
        return data

    @field_validator("host")
    @classmethod
    def _host_name(cls, host: str) -> str:
        if not _HOST.fullmatch(host):
            raise ValueError("host must be a host name, like github.com")
        return host.lower()

    @model_validator(mode="after")
    def _org_name(self) -> "OrgSource":
        if self.kind == "git":
            if not is_repo_path(self.org):
                raise ValueError("org must be the path its repos share, like acme or acme/platform")
            self.repo_urls()
        elif self.repos:
            raise ValueError("repos: lists a plain git org's repos (GitHub and GitLab list theirs)")
        elif self.kind == "gitlab":
            if not _GROUP.fullmatch(self.org) or self.org.endswith((".git", ".atom")):
                raise ValueError("org must be a GitLab group or user, like acme or acme/platform")
        elif not _ORG.fullmatch(self.org):
            raise ValueError("org must be a GitHub org or user name, like acme")
        return self

    def repo_urls(self) -> dict[str, str]:
        """Kind git: each listed repo's full path (as on its host) -> its URL. Raises
        ValueError for a URL cairn won't clone, or one off this org's host and path."""
        if not self.repos:
            raise ValueError("a plain git org lists its repos: repos: [https://host/org/repo.git]")
        found: dict[str, str] = {}
        for n, url in enumerate(self.repos, start=1):
            parsed = repo_url(url)  # a URL is never echoed: it may hold a token
            if parsed is None:
                raise ValueError(
                    f"repo {n}: give an https URL (https://host/path, no login in it) or an ssh "
                    "one (git@host:path)"
                )
            host, path = parsed
            if host != self.host or not path.lower().startswith(f"{self.org.lower()}/"):
                raise ValueError(f"repo {n} ({host}/{path}) isn't a repo of {self.host}/{self.org}")
            if path.lower() in {name.lower() for name in found}:
                raise ValueError(f"repo {n}: {path} is listed twice")
            found[path] = url.strip()
        return found


class CairnConfig(Frozen):
    card_budget: int = Field(default=800, ge=200, le=4000)
    index_threshold: int = Field(default=50, ge=5)
    max_depth: int = Field(default=4, ge=1, le=10)
    max_file_bytes: int = Field(default=1_000_000, ge=10_000)
    ignore_dirs: tuple[str, ...] = ()
    stop_tables: tuple[str, ...] = ()
    stop_aliases: tuple[str, ...] = ()
    stale_file_threshold: int = Field(default=50, ge=1)
    orgs: tuple[OrgSource, ...] = ()
    # Uncloned org repos INDEX lists (those the workspace depends on first), from the caches.
    org_index_repos: int = Field(default=15, ge=0, le=100)
