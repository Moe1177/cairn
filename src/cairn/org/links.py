"""How the workspace's own repos meet the org's uncloned ones: which org repos define the packages
local repos depend on, for INDEX and for an org repo's card.

Read from the caches only (the org's package index and repo catalog): mapping a folder makes no
network calls. Org text a repo controls (its description) stays out of INDEX, which every
session loads; names, languages and counts go in.
"""

import re
from collections.abc import Mapping, Sequence

from cairn.model.graph import FactKind, Repo, Workspace
from cairn.org.catalog import CatalogRepo, OrgCatalog
from cairn.org.packages import OrgPackage, PackageIndex, org_packages, plain_name
from cairn.security.text import clean_inline

_LOCAL_SHOWN = 3
_SAME = {"pypi": "python"}  # what a scan calls an ecosystem, as the org's index calls it
_PY_SEPARATORS = re.compile(r"[-_.]+")


def local_clones(workspace: Workspace) -> set[str]:
    """host/owner/name of every workspace repo with a remote, lower case."""
    return {r.remote.lower().removesuffix(".git") for r in workspace.repos if r.remote}


def cloned_as(workspace: Workspace, name: str) -> Repo | None:
    """The workspace repo whose remote is `owner/name` (or host/owner/name), if one is."""
    wanted = name.strip().lower().removesuffix(".git").strip("/")
    if "/" not in wanted:
        return None
    for repo in workspace.repos:
        remote = (repo.remote or "").lower().removesuffix(".git")
        if remote == wanted or remote.endswith("/" + wanted):
            return repo
    return None


def package_key(name: str) -> tuple[str, str]:
    """(ecosystem, name) as both sides write them: a scan's `pypi:` is the org's `python:`,
    Python names compare as pip compares them, and a Go module's major versions are one."""
    ecosystem, _, bare = name.strip().lower().partition(":")
    ecosystem = _SAME.get(ecosystem, ecosystem)
    if ecosystem == "python":
        bare = _PY_SEPARATORS.sub("-", bare)
    return ecosystem, plain_name(f"{ecosystem}:{bare}")


def local_users(workspace: Workspace, packages: Sequence[OrgPackage]) -> dict[str, tuple[str, ...]]:
    """Org repo (owner/name) -> the workspace repos that depend on a package it defines."""
    homes = {package_key(p.name): p.home for p in packages if p.home}
    found: dict[str, set[str]] = {}
    for repo in workspace.repos:
        for fact in repo.contracts.consumes:
            if fact.kind is FactKind.PACKAGE:
                home = homes.get(package_key(fact.value))
                if home:
                    found.setdefault(home, set()).add(repo.id)
    return {home: tuple(sorted(ids)) for home, ids in found.items()}


def index_lines(
    workspace: Workspace,
    indexes: Sequence[PackageIndex],
    catalogs: Mapping[str, OrgCatalog],
    *,
    budget: int,
) -> list[str]:
    """INDEX's org section: the uncloned org repos the workspace depends on, then those whose
    packages most org repos use, `budget` lines in all."""
    if budget <= 0 or not indexes:
        return []
    clones = local_clones(workspace)
    rows: list[tuple[int, int, str, str, tuple[str, ...]]] = []
    for index in indexes:
        packages = org_packages(index)
        here = local_users(workspace, packages)
        reach: dict[str, int] = {}
        for package in packages:
            if package.home:
                reach[package.home] = max(reach.get(package.home, 0), len(package.users))
        languages = {r.name: r.language for r in _repos(catalogs.get(index.org.lower()))}
        for home, users in reach.items():
            if f"{index.host}/{home}".lower() in clones:
                continue  # cloned here: its own line above says the rest
            rows.append(
                (len(here.get(home, ())), users, home, languages.get(home, ""), here.get(home, ()))
            )
    rows.sort(key=lambda row: (-row[0], -row[1], row[2].lower()))
    if not rows:
        return []
    lines = [
        "",
        "## Org repos, not cloned (repo_card <owner/name> describes one; read_org_file reads it)",
    ]
    for _, users, home, language, here in rows[:budget]:
        stack = f" · {clean_inline(language, 40)}" if language else ""
        shown = ", ".join(clean_inline(r, 40) for r in here[:_LOCAL_SHOWN])
        more = f" +{len(here) - _LOCAL_SHOWN}" if len(here) > _LOCAL_SHOWN else ""
        used = f" · used here by {shown}{more}" if here else ""
        lines.append(f"- {home}{stack}{used} · its packages: {users} org repos use them")
    return lines


def _repos(catalog: OrgCatalog | None) -> tuple[CatalogRepo, ...]:
    return catalog.repos if catalog else ()


def card_extras(workspace: Workspace, index: PackageIndex | None, repo: str) -> list[str]:
    """An org repo card's package lines: what it defines, which org libraries it uses, and
    which workspace repos depend on it."""
    if index is None:
        return ["- Packages: not read yet (org_packages reads them)."]
    packages = org_packages(index)
    lowered = repo.lower()
    own = [p for p in packages if p.home.lower() == lowered]
    lines = []
    if own:
        lines.append(
            "- Defines: "
            + ", ".join(
                f"{p.name.partition(':')[2]} ({len(p.users)} org repos use it)" for p in own[:10]
            )
        )
    record = next((r for r in index.repos if r.repo.lower() == lowered), None)
    if record is not None:
        homes = {package_key(p.name): p for p in packages if p.home and p.home.lower() != lowered}
        used = sorted(
            {
                homes[key].name.partition(":")[2]
                for u in record.uses
                if (key := package_key(u.name)) in homes
            }
        )
        if used:
            lines.append(f"- Uses the org's: {', '.join(used[:12])}")
    here = next(
        (ids for home, ids in local_users(workspace, packages).items() if home.lower() == lowered),
        (),
    )
    if here:
        lines.append(f"- Used by these workspace repos: {', '.join(here)}")
    return lines
