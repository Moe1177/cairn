"""User configuration (.cairn/config.yaml). Every field has a safe default."""

import re
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from cairn.model.graph import Frozen

_ORG = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
# A GitLab group, with any subgroups (acme/platform): segments as GitLab allows them.
_GROUP = re.compile(
    r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,254}(?:/[A-Za-z0-9_][A-Za-z0-9_.-]{0,254}){0,19}$"
)
_HOST = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?(?:\.[A-Za-z0-9-]{1,63})+$")


class OrgSource(Frozen):
    """An org (or user) on a code host whose repos cairn reads over the API, never cloning. On
    GitLab, the org is a group, a subgroup (acme/platform) or a user."""

    org: str
    host: str = "github.com"
    # Which API the host speaks: gitlab for gitlab.com and gitlab.* hosts unless said otherwise.
    kind: Literal["github", "gitlab"] = "github"

    @model_validator(mode="before")
    @classmethod
    def _infer_kind(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data.get("kind"):
            host = str(data.get("host") or "github.com").lower()
            gitlab = host == "gitlab.com" or host.startswith("gitlab.")
            return {**data, "kind": "gitlab" if gitlab else "github"}
        return data

    @field_validator("host")
    @classmethod
    def _host_name(cls, host: str) -> str:
        if not _HOST.fullmatch(host):
            raise ValueError("host must be a host name, like github.com")
        return host.lower()

    @model_validator(mode="after")
    def _org_name(self) -> "OrgSource":
        if self.kind == "gitlab":
            if not _GROUP.fullmatch(self.org) or self.org.endswith((".git", ".atom")):
                raise ValueError("org must be a GitLab group or user, like acme or acme/platform")
        elif not _ORG.fullmatch(self.org):
            raise ValueError("org must be a GitHub org or user name, like acme")
        return self


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
