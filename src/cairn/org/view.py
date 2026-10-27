"""The org's uncloned repos where an agent already looks: resolve_repo's answers, repo_card, and
INDEX. The catalog is read over the API when its cache is a day old (resolve_repo and repo_card
only, never under the workspace lock); INDEX reads the caches alone, so mapping a folder stays
offline.
"""

import contextlib
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from cairn.config import CairnConfig, OrgSource
from cairn.errors import CairnError
from cairn.load import load_config
from cairn.model.graph import Workspace
from cairn.org.access import with_client
from cairn.org.catalog import (
    CatalogIndex,
    OrgCatalog,
    build_catalog,
    find_repo,
    find_repos,
    load_catalog,
    needs_build,
    render_matches,
    render_org_card,
    save_catalog,
)
from cairn.org.links import card_extras, index_lines, local_clones
from cairn.org.packages import load_index
from cairn.paths import org_catalog_file, org_packages_file
from cairn.security.text import clean_inline

ORG_MATCHES = 3
RETRY_AFTER = 300.0  # seconds before reading an org again after a read failed
_LOCK = threading.Lock()
_Key = tuple[str, str, str]  # (workspace, host, org)
_INDEXES: dict[_Key, CatalogIndex] = {}  # the cached catalog, its words counted
_FAILED: dict[_Key, float] = {}  # monotonic time of the last failed read
# INDEX's org lines, kept while the cache files they came from are unchanged.
_LINES: dict[tuple[object, ...], list[str]] = {}


def catalog_index(ws_root: Path, source: OrgSource, *, refresh: bool = False) -> CatalogIndex:
    """The org's catalog, ready to search: from memory or the cache while under a day old, else
    read over the API (one request per 100 repos). When that read fails, a day-old catalog is
    still used, and the org isn't read again for five minutes."""
    key = (str(ws_root), source.host, source.org.lower())
    path = org_catalog_file(ws_root, source.host, source.org)
    now = datetime.now(UTC)
    with _LOCK:
        held = _INDEXES.get(key)
        if held is not None and not refresh and not needs_build(held.catalog, now):
            return held
        cached = load_catalog(path) if held is None else held.catalog
        if cached is not None and not refresh and not needs_build(cached, now):
            return _keep(key, cached)
        failed = _FAILED.get(key)
        if failed is not None and time.monotonic() - failed < RETRY_AFTER:
            if cached is not None:
                return _keep(key, cached)
            raise CairnError(f"couldn't read {source.org} a moment ago; trying again shortly")
        try:
            catalog = with_client(
                source, lambda client: build_catalog(client, source.org, source.host)
            )
        except CairnError:
            _FAILED[key] = time.monotonic()
            if cached is not None:
                return _keep(key, cached)  # a day-old listing beats none
            raise
        _FAILED.pop(key, None)
        with contextlib.suppress(OSError):  # a read-only workspace still gets the answer
            save_catalog(path, catalog)
        return _keep(key, catalog)


def _keep(key: _Key, catalog: OrgCatalog) -> CatalogIndex:
    held = _INDEXES.get(key)
    if held is None or held.catalog is not catalog:
        held = CatalogIndex.of(catalog)
        _INDEXES[key] = held
    return held


def org_matches(ws_root: Path, workspace: Workspace, query: str) -> tuple[list[str], list[str]]:
    """resolve_repo's lines for uncloned org repos a phrase may mean (none without orgs), and a
    note for each org that couldn't be searched."""
    clones = local_clones(workspace)
    lines: list[str] = []
    problems: list[str] = []
    for source in load_config(ws_root).orgs:
        try:
            index = catalog_index(ws_root, source)
        except CairnError as exc:
            problems.append(f"(org {source.org} not searched: {clean_inline(str(exc), 160)})")
            continue
        matches = [
            m
            for m in find_repos(index, query, limit=ORG_MATCHES + len(clones))
            if f"{source.host}/{m.repo.name}".lower() not in clones
        ][:ORG_MATCHES]
        lines += render_matches(index.catalog, matches)
    return lines, problems


def org_card(ws_root: Path, workspace: Workspace, name: str) -> str | None:
    """The card of an uncloned org repo called `name` (its name, owner/name, or with the host
    in front), or None. Only configured orgs are read."""
    for source in load_config(ws_root).orgs:
        inside = _inside_org(source, name)
        if inside is None:
            continue
        try:
            index = catalog_index(ws_root, source)
        except CairnError:
            continue
        repo = find_repo(index.catalog, inside)
        if repo is not None:
            packages = load_index(org_packages_file(ws_root, source.host, source.org))
            extras = card_extras(workspace, packages, repo.name)
            return render_org_card(repo, extras, searchable=source.kind != "git")
    return None


def _inside_org(source: OrgSource, name: str) -> str | None:
    """`name`'s path inside the org, or None when it names another host or owner. On GitLab a
    path without the org is one inside it (a subgroup's repo)."""
    wanted = name.strip().strip("/").lower().removesuffix(".git")
    first = wanted.partition("/")[0]
    if first == source.host:  # host/owner/name
        wanted = wanted.partition("/")[2]
    elif "." in first and source.kind == "github":
        return None  # another host (a GitHub owner has no dot; a GitLab group may)
    prefix = f"{source.org.lower()}/"
    if wanted.startswith(prefix):
        return wanted[len(prefix) :]
    if "/" in wanted and source.kind == "github":
        return None  # another owner's
    return wanted


def org_index_lines(ws_root: Path, workspace: Workspace, config: CairnConfig) -> list[str]:
    """INDEX's org section, from the caches only: nothing is fetched while mapping. Worked out
    again only when a cache file or the workspace's dependencies changed."""
    files = [
        path
        for source in config.orgs
        for path in (
            org_packages_file(ws_root, source.host, source.org),
            org_catalog_file(ws_root, source.host, source.org),
        )
    ]
    stamps = tuple(_stamp(path) for path in files)
    if not any(stamps[0::2]):
        return []  # no org's packages read yet: nothing links the workspace to the org
    needs = tuple(
        (r.id, r.remote, tuple(f.value for f in r.contracts.consumes)) for r in workspace.repos
    )
    key = (str(ws_root), config.org_index_repos, stamps, hash(needs))
    if key not in _LINES:
        indexes, catalogs = [], {}
        for source in config.orgs:
            index = load_index(org_packages_file(ws_root, source.host, source.org))
            if index is not None:
                indexes.append(index)
            catalog = load_catalog(org_catalog_file(ws_root, source.host, source.org))
            if catalog is not None:
                catalogs[source.org.lower()] = catalog
        _LINES.clear()  # one workspace's lines at a time: the map is rewritten often
        _LINES[key] = index_lines(workspace, indexes, catalogs, budget=config.org_index_repos)
    return list(_LINES[key])


def _stamp(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size
