"""User configuration (.cairn/config.yaml). Every field has a safe default."""

import re

from pydantic import Field, field_validator

from cairn.model.graph import Frozen

_ORG = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_HOST = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?(?:\.[A-Za-z0-9-]{1,63})+$")


class OrgSource(Frozen):
    """An org (or user) on a code host whose repos cairn reads over the API, never cloning."""

    org: str
    host: str = "github.com"

    @field_validator("org")
    @classmethod
    def _org_name(cls, org: str) -> str:
        if not _ORG.fullmatch(org):
            raise ValueError("org must be a GitHub org or user name, like acme")
        return org

    @field_validator("host")
    @classmethod
    def _host_name(cls, host: str) -> str:
        if not _HOST.fullmatch(host):
            raise ValueError("host must be a host name, like github.com")
        return host.lower()


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
