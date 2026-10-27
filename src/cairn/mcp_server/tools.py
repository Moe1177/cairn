"""cairn MCP tool logic: workspace path + arguments in, short capped markdown out."""

import contextlib
import functools
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from cairn.config import OrgSource
from cairn.discover.git import head_sha
from cairn.emit import write_outputs
from cairn.errors import CairnError
from cairn.integrations.claude import sync_claude
from cairn.load import load_authored, load_config
from cairn.mcp_server.query import answer as query_answer
from cairn.model.graph import Confidence, FactKind, Package, Repo, Workspace
from cairn.org.access import client_for, forget_client, org_repo, pick_org
from cairn.org.files import folder_entries, render_folder, render_missing
from cairn.org.links import cloned_as
from cairn.org.packages import (
    build_index,
    find_packages,
    load_index,
    needs_build,
    org_packages,
    render_choices,
    render_package,
    render_packages,
    save_index,
    usage_files,
)
from cairn.org.profile import (
    build_profile,
    is_degraded,
    is_stale,
    load_profile,
    render_profile,
    save_profile,
)
from cairn.org.similar import find_similar, render_similar
from cairn.org.view import org_card, org_matches
from cairn.paths import cards_dir, org_packages_file, org_profile_file
from cairn.remote.host import CodeHost
from cairn.render.card import relate_line
from cairn.render.links import Neighbor, hidden_count, neighbors, render_links, repo_at
from cairn.resolve import resolve_repo
from cairn.scan import ScanResult, scan_workspace
from cairn.security.redact import redact
from cairn.security.text import clean_inline
from cairn.store.lock import workspace_lock
from cairn.store.workspace_store import load_workspace

MAX_LINES = 30
MAX_FILE_LINES = 400  # an org file is read to learn its approach; past this, it is a dataset
MAX_FILE_CHARS = 40_000
MAX_LINE_CHARS = 400


def rescan(ws_root: Path) -> ScanResult:
    with workspace_lock(ws_root):
        result = scan_workspace(ws_root)
        write_outputs(ws_root, result)
        sync_claude(ws_root)
        return result


LOCK_WAIT = 5.0
T = TypeVar("T")
_NO_RESCAN = threading.local()


_BUSY_NOTE = (
    "\n(note: another cairn process is updating this workspace; this answer may be slightly stale)"
)


def _under_lock(ws_root: Path, call: Callable[[], T]) -> tuple[T, str]:
    """`call()` under the workspace lock, so reads never race a concurrent rescan, and a note
    to append to the answer ("" normally)."""
    try:
        with workspace_lock(ws_root, timeout=LOCK_WAIT):
            return call(), ""
    except CairnError as exc:
        if "still updating" not in str(exc):
            raise
    # Another scan holds the lock: answer from the map on disk (atomically written, so
    # never half-updated) rather than leaving the agent waiting up to a minute.
    _NO_RESCAN.active = True
    try:
        return call(), _BUSY_NOTE
    finally:
        _NO_RESCAN.active = False


def locked(func: Callable[..., str]) -> Callable[..., str]:
    """Run a tool under the workspace lock so reads never race a concurrent rescan."""

    @functools.wraps(func)
    def wrapper(ws_root: Path, *args: object, **kwargs: object) -> str:
        text, note = _under_lock(ws_root, lambda: func(ws_root, *args, **kwargs))
        return text + note

    return wrapper


def _workspace(ws_root: Path) -> Workspace:
    return load_workspace(ws_root) or rescan(ws_root).workspace


def _fresh(ws_root: Path, repo: Repo) -> Workspace:
    """Spec §17: re-scan when the repo's HEAD moved since the map was written."""
    if getattr(_NO_RESCAN, "active", False):
        return _workspace(ws_root)
    current = head_sha(ws_root / repo.path)  # remembered until HEAD moves: no git process
    if current and repo.head_sha and current != repo.head_sha:
        return rescan(ws_root).workspace
    return _workspace(ws_root)


def _cap(lines: list[str]) -> list[str]:
    if len(lines) <= MAX_LINES:
        return lines
    return [*lines[:MAX_LINES], f"…(+{len(lines) - MAX_LINES} more)"]


def _find(ws_root: Path, name: str) -> tuple[Workspace, Repo | None, str]:
    workspace = _workspace(ws_root)
    lowered = name.strip().lower()
    for repo in workspace.repos:
        if lowered == repo.id.lower() or lowered in (a.lower() for a in repo.aliases):
            return workspace, repo, ""
    owner = _package_owner(workspace, lowered)
    if owner is not None:
        return workspace, owner[0], ""
    matches = resolve_repo(workspace, load_authored(ws_root), name, limit=3)
    if matches and matches[0].score == 1.0:
        return workspace, workspace.repo(matches[0].repo_id), ""
    hint = ", ".join(m.repo_id for m in matches) or "none"
    return workspace, None, f"No repo named '{name}'. Did you mean: {hint}? (use resolve_repo)"


def find_repo(ws_root: Path, name: str) -> tuple[Repo | None, str]:
    """The repo a name or alias means, or None and a hint saying why not."""
    _, found, message = _find(ws_root, name)
    return found, message


LinksView = tuple[str, tuple[Neighbor, ...], int]


def links_view(
    ws_root: Path, repo: str, start: Path | None, *, include_unconfirmed: bool = False
) -> LinksView | str:
    """(repo id, its linked repos, how many more only unconfirmed links reach), or a message.
    No name means the repo that contains `start` (the folder the session runs in)."""
    view, _ = _under_lock(ws_root, lambda: _links_view(ws_root, repo, start, include_unconfirmed))
    return view


def _links_view(
    ws_root: Path, repo: str, start: Path | None, include_unconfirmed: bool
) -> LinksView | str:
    workspace = _workspace(ws_root)
    if repo.strip():
        found, message = find_repo(ws_root, repo)
        if found is None:
            return message
    else:
        found = repo_at(workspace, ws_root, start) if start is not None else None
        if found is None:
            return (
                "Not inside one of this workspace's repos, so name one "
                "(resolve_repo finds a repo from a description)."
            )
    workspace = _fresh(ws_root, found)
    linked = neighbors(workspace, found.id, include_unconfirmed=include_unconfirmed)
    hidden = 0 if include_unconfirmed else hidden_count(workspace, found.id)
    return found.id, linked, hidden


def links_text(
    ws_root: Path, repo: str = "", start: Path | None = None, include_unconfirmed: bool = False
) -> str:
    view = links_view(ws_root, repo, start, include_unconfirmed=include_unconfirmed)
    if isinstance(view, str):
        return view
    repo_id, linked, hidden = view
    return render_links(repo_id, linked, hidden=hidden, show_all="include_unconfirmed=true")


def _package_owners(workspace: Workspace, lowered: str) -> list[tuple[Repo, Package]]:
    """Every repo whose monorepo contains a package with this exact name (spec §21.4)."""
    return [
        (repo, package)
        for repo in workspace.repos
        for package in repo.packages
        if package.name.lower() == lowered
    ]


def _package_owner(workspace: Workspace, lowered: str) -> tuple[Repo, Package] | None:
    owners = _package_owners(workspace, lowered)
    return owners[0] if owners else None


def _names_a_repo(workspace: Workspace, lowered: str) -> bool:
    return any(
        lowered == r.id.lower() or lowered in (a.lower() for a in r.aliases)
        for r in workspace.repos
    )


def resolve_text(ws_root: Path, query: str) -> str:
    """Workspace repos a phrase means (read under the workspace lock), then uncloned org repos
    (after it: reading the org's listing must never hold up a rescan)."""
    (workspace, local, exact), note = _under_lock(ws_root, lambda: _resolve_local(ws_root, query))
    if exact:
        return "\n".join(local) + note
    org, problems = org_matches(ws_root, workspace, query)
    if not local and not org:
        known = ", ".join(r.id for r in workspace.repos[:MAX_LINES])
        return "\n".join([f"No repo matches '{query}'. Repos: {known}", *problems]) + note
    return "\n".join([*local, *org, *problems]) + note


def _resolve_local(ws_root: Path, query: str) -> tuple[Workspace, list[str], bool]:
    """(the map, its lines for the phrase, whether they settle it: a repo or package by that
    very name)."""
    workspace = _workspace(ws_root)
    lowered = query.strip().lower()
    # A repo's own name always wins; then every repo holding a package by that name.
    owners = [] if _names_a_repo(workspace, lowered) else _package_owners(workspace, lowered)
    if owners:
        lines = [
            clean_inline(
                f"- {repo.id}: package {package.name} at `{package.path}` "
                f"→ .cairn/cards/{repo.id}.md",
                400,
            )
            for repo, package in owners[:MAX_LINES]
        ]
        return workspace, lines, True
    matches = resolve_repo(workspace, load_authored(ws_root), query, limit=5)
    lines = [
        f"- {m.repo_id} ({m.score:.2f}): {m.one_liner} · `{m.path}` → .cairn/cards/{m.repo_id}.md"
        for m in matches
    ]
    return workspace, lines, bool(matches) and matches[0].score == 1.0


def card_text(ws_root: Path, repo: str) -> str:
    """A workspace repo's card, else an uncloned org repo's (from the org's listing)."""
    workspace, found, message = _find(ws_root, repo)
    found = found or cloned_as(workspace, repo)  # owner/name of a repo cloned here
    if found is None:
        org = org_card(ws_root, workspace, repo)
        return org if org is not None else message
    return _local_card(ws_root, found.id)


@locked
def _local_card(ws_root: Path, repo_id: str) -> str:
    _, found, message = _find(ws_root, repo_id)
    if found is None:
        return message
    _fresh(ws_root, found)
    path = cards_dir(ws_root) / f"{found.id}.md"
    if not path.is_file():
        return f"No card for {found.id} yet; call refresh."
    return path.read_text(encoding="utf-8")


@locked
def related_text(
    ws_root: Path, repo: str, edge_type: str | None = None, include_unconfirmed: bool = False
) -> str:
    _, found, message = _find(ws_root, repo)
    if found is None:
        return message
    workspace = _fresh(ws_root, found)
    edges = [
        e
        for e in workspace.edges_for(found.id)
        if (edge_type is None or e.type.value == edge_type)
        and (include_unconfirmed or e.confidence is not Confidence.AMBIGUOUS)
    ]
    if not edges:
        return f"No matching relationships for {found.id}."
    edges.sort(key=lambda e: (-e.confidence.rank, -e.score, e.key))
    lines = _cap([relate_line(found.id, e) for e in edges])
    return "\n".join([f"{found.id} relationships ({len(edges)}):", *lines])


@locked
def find_across_text(ws_root: Path, query: str, kind: str | None = None) -> str:
    workspace = _workspace(ws_root)
    needle = query.strip().lower()
    lines: list[str] = []
    for repo in workspace.repos:
        exposes = tuple(f for f in repo.contracts.exposes if f.kind is not FactKind.GIT_ROOT)
        sides = (("exposes", exposes), ("consumes", repo.contracts.consumes))
        for direction, facts in sides:
            for fact in facts:
                if fact.kind is FactKind.COMPOSE_SERVICE:
                    continue  # internal service-to-repo wiring; the edges show the result
                if needle not in fact.value.lower() or (kind and fact.kind.value != kind):
                    continue
                ev = fact.evidence[0] if fact.evidence else None
                where = f" ({ev.file}:{ev.line})" if ev else ""
                label = fact.kind.value.replace("_", " ")
                line = f"- {repo.id} {direction} {label} '{fact.value}'{where}"
                lines.append(clean_inline(line, 400))
    return "\n".join(_cap(lines)) if lines else f"Nothing in the map matches '{query}'."


@locked
def refresh_text(ws_root: Path) -> str:
    previous = load_workspace(ws_root)
    before = {r.id: r.head_sha for r in previous.repos} if previous else {}
    workspace = rescan(ws_root).workspace
    changed = [r.id for r in workspace.repos if before.get(r.id) != r.head_sha]
    detail = f": {', '.join(changed[:10])}" if changed else ""
    return (
        f"Refreshed {len(workspace.repos)} repos ({len(changed)} changed{detail}); "
        f"{len(workspace.edges)} relationships."
    )


def query_text(ws_root: Path, repo: str, question: str) -> str:
    """Where in the code `question` is answered: grep first, the code graph as a backstop. Only
    loading the map holds the workspace lock: a slow search never blocks a hook's refresh."""

    def target() -> tuple[Workspace, Repo] | str:
        _, found, message = _find(ws_root, repo)
        if found is None:
            return message
        workspace = _fresh(ws_root, found)
        return workspace, workspace.repo(found.id) or found

    resolved, note = _under_lock(ws_root, target)
    if isinstance(resolved, str):
        return resolved + note
    workspace, found = resolved
    header, lines, notes = query_answer(ws_root, workspace, found, question)
    return "\n".join([header, *_cap(lines), *notes]) + note


def similar_text(ws_root: Path, task: str, terms: list[str], org: str = "") -> str:
    """The org's existing implementations of `task`, over the host's API (nothing is cloned).
    Reads only the config, so it never waits on the workspace lock."""
    source = pick_org(load_config(ws_root).orgs, org)
    if not task.strip() and not any(t.strip() for t in terms):
        return "Say what you're building (task) and a few terms its code would contain (terms)."
    return render_similar(
        _with_client(source, lambda client: find_similar(client, source.org, task, terms))
    )


_PROFILE_LOCK = threading.Lock()  # two calls at once read the org once


def profile_text(ws_root: Path, org: str = "", *, refresh: bool = False) -> str:
    """The org's stack, from the cache while it is under a week old, else read over the API
    (about 15 s). Reads only the config, so it never waits on the workspace lock."""
    source = pick_org(load_config(ws_root).orgs, org)
    path = org_profile_file(ws_root, source.host, source.org)
    with _PROFILE_LOCK:
        profile = None if refresh else load_profile(path)
        if profile is None or is_stale(profile, datetime.now(UTC)):
            profile = _with_client(
                source, lambda client: build_profile(client, source.org, source.host)
            )
            # A read-only workspace still gets the answer, just not the cache.
            with contextlib.suppress(OSError):
                if not is_degraded(profile):
                    save_profile(path, profile)
    return render_profile(profile)


_PACKAGES_LOCK = threading.Lock()


def packages_text(
    ws_root: Path, name: str = "", query: str = "", org: str = "", *, refresh: bool = False
) -> str:
    """The org's own packages, or one of them with its users and code that calls it. Read over
    the API when the cache is a day old (only repos pushed since are read again)."""
    source = pick_org(load_config(ws_root).orgs, org)
    path = org_packages_file(ws_root, source.host, source.org)
    with _PACKAGES_LOCK:
        index = load_index(path)
        if index is None or refresh or needs_build(index, datetime.now(UTC)):
            previous = index
            index = _with_client(
                source,
                lambda client: build_index(client, source.org, source.host, previous=previous),
            )
            with contextlib.suppress(OSError):  # a read-only workspace still gets the answer
                save_index(path, index)
    packages = org_packages(index)
    if not name.strip():
        return render_packages(index, packages, query=query)
    found = find_packages(packages, name)
    if len(found) != 1:
        return render_choices(found, name)
    try:
        files = _with_client(source, lambda client: usage_files(client, source.org, found[0]))
    except CairnError as exc:  # the package is still worth showing without its usages
        return render_package(index, found[0], str(exc))
    return render_package(index, found[0], files)


def org_file_text(ws_root: Path, repo: str, path: str, org: str = "") -> str:
    """A file from an org repo's default branch, numbered like a code view, with secrets masked
    as in every snippet cairn shows. A folder ("" for the root) lists what it holds, and a path
    that isn't there names the files it most likely meant: one more request, the repo's file
    list, kept for a few minutes."""
    source = pick_org(load_config(ws_root).orgs, org)
    full = org_repo(source, repo)
    inside = path.strip().strip("/")
    text = _with_client(source, lambda client: client.read_file(full, inside)) if inside else None
    if text is None:
        paths, cut = _repo_files(ws_root, source, full)
        if inside in paths:
            return f"{full}/{inside} is binary or over 200 KB: not shown."
        entries = folder_entries(paths, inside)
        if entries:
            return render_folder(full, inside, entries, cut=cut)
        return render_missing(full, inside, paths, cut=cut)
    lines = text.splitlines()
    shown, size = [], 0
    for line in lines[:MAX_FILE_LINES]:
        size += len(line) + 1
        if size > MAX_FILE_CHARS:  # a minified file is one huge line
            break
        shown.append(redact(line[:MAX_LINE_CHARS]))
    body = "\n".join(f"{n:>5}  {line}" for n, line in enumerate(shown, start=1))
    more = f"\n… {len(lines) - len(shown)} more lines" if len(lines) > len(shown) else ""
    return f"{full}/{inside} ({len(lines)} lines)\n{body}{more}"


_FILES_TTL = 300.0  # seconds: an agent browsing a repo lists several folders in a row
_FILES_HELD = 32
_FILES: dict[tuple[str, str], tuple[float, tuple[str, ...], bool]] = {}
_FILES_LOCK = threading.Lock()


def _repo_files(ws_root: Path, source: OrgSource, full: str) -> tuple[tuple[str, ...], bool]:
    """Every file on `full`'s default branch, and whether the list was cut short. The branch
    comes from the org's package index when it was read, else HEAD names it."""
    key = (source.host, full.lower())
    with _FILES_LOCK:
        held = _FILES.get(key)
    if held is not None and time.monotonic() - held[0] < _FILES_TTL:
        return held[1], held[2]
    index = load_index(org_packages_file(ws_root, source.host, source.org))
    branch = next(
        (r.branch for r in (index.repos if index else ()) if r.repo.lower() == full.lower()),
        "",
    )
    paths, cut = _with_client(source, lambda client: client.tree(full, branch or "HEAD"))
    with _FILES_LOCK:
        if len(_FILES) >= _FILES_HELD:
            _FILES.pop(next(iter(_FILES)))  # the oldest
        _FILES[key] = (time.monotonic(), paths, cut)
    return paths, cut


def _with_client(source: OrgSource, call: Callable[[CodeHost], T]) -> T:
    try:
        return call(client_for(source))
    except CairnError as exc:
        if "rejected the token" in str(exc):
            forget_client(source)  # read the token again next time: a new login then works
        raise
