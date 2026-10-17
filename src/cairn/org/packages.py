"""The org's own packages: the libraries its repos define and use from one another (an internal
SDK, a service's client, a logging or test helper), where each is defined, which repos use it,
and which files to read to see it used.

An agent adding logging, retries or a service client to an org repo should reach for the org's
own library before a public one, and call it the way sibling repos do. Nothing is cloned: every
active repo's file tree and manifests are read over the API (hashicorp's 604 repos: about 35 s),
then cached. A refresh rereads only the repos pushed since, so a big org costs the full read once.
"""

import re
import time
from collections import Counter
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from cairn.detectors.manifests import dig, parse_json, parse_toml
from cairn.errors import CairnError
from cairn.model.graph import Frozen
from cairn.org.profile import (
    ECOSYSTEMS,
    MANIFEST,
    PACKAGE_NAME,
    active_repos,
    manifests,
    older_than,
    parse_manifest,
    save_cache,
    under_org,
)
from cairn.org.similar import weight
from cairn.remote.github import GitHub, RepoInfo
from cairn.security.redact import redact
from cairn.security.text import clean_inline

MAX_AGE = timedelta(days=1)  # a refresh rereads only what was pushed since: cheap
MAX_REPOS = 10_000
MANIFESTS_PER_REPO = 150  # a monorepo's packages, shallowest first (grafana/grafana has 83)
# Requests left for the agent's other calls: an org too big for one hour's API budget is read
# over several calls, most recently pushed repos first.
RESERVE = 500
LIST_LIMIT = 100  # at hashicorp, every package 2+ repos share; past that, a query finds it
_WORKERS = 16
_USERS_SHOWN = 30
_FILES_SHOWN = 5
_DESCRIPTION = 120
_FRAGMENT = 160
_CODE = 0.4  # weight() of a test file: anything lower is docs or data
_GO_MAJOR = re.compile(r"/v\d+$")
# Code that shows a package off or tests it, not a repo's own project.
_EXAMPLE = re.compile(
    r"(?:^|/)(?:testdata|test-fixtures|fixtures?|examples?|samples?|demos?)/", re.IGNORECASE
)
INDEX_VERSION = 1  # bumped when what is read from a repo changes: older records are read again
_LOCKFILE = re.compile(r"(?:^|/)(?:go\.sum|[^/]*\.lock|package-lock\.json|pnpm-lock\.yaml)$")


class Defined(Frozen):
    name: str  # ecosystem:name
    path: str  # its manifest, inside the repo
    description: str = ""


class Used(Frozen):
    name: str  # ecosystem:name
    path: str  # the manifest that asks for it


class RepoPackages(Frozen):
    repo: str  # owner/name
    pushed: str = ""
    branch: str = ""
    fork: bool = False
    description: str = ""
    defines: tuple[Defined, ...] = ()
    uses: tuple[Used, ...] = ()
    failed: bool = False  # its tree or a manifest couldn't be read: reread next time


class PackageIndex(Frozen):
    version: int = 0  # INDEX_VERSION of the cairn that read it
    org: str
    host: str
    built: str  # ISO time, UTC
    ms: float
    repos: tuple[RepoPackages, ...] = ()  # most recently pushed first
    reread: int = 0  # repos read this time; the rest came from the last index
    unread: int = 0  # active repos due a read that didn't get one: the API budget ran low


@dataclass(frozen=True)
class OrgPackage:
    name: str  # ecosystem:name
    home: str  # owner/name of the repo that defines it, "" when no active repo does
    path: str  # its manifest in `home`, "" when not read
    description: str
    users: tuple[tuple[str, tuple[str, ...]], ...]  # (repo, its manifests asking for it)


def build_index(
    client: GitHub,
    org: str,
    host: str = "github.com",
    *,
    previous: PackageIndex | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> PackageIndex:
    """Every active repo's packages: those unchanged since `previous` are kept, the rest read."""
    started = time.perf_counter()
    usable = (
        previous is not None
        and previous.org.lower() == org.lower()
        and previous.version == INDEX_VERSION
    )
    left = client.remaining()
    if previous is not None and usable and left is not None and left < RESERVE:
        return previous  # nothing to read with until the budget refills: keep what there is
    repos = active_repos(client, org, MAX_REPOS, max_pages=MAX_REPOS // 100)
    if not repos:
        raise CairnError(f"{org} has no repos cairn can read (or none that aren't archived)")
    kept = {r.repo.lower(): r for r in previous.repos} if previous and usable else {}
    todo = [repo for repo in repos if not _current(kept.get(repo.name.lower()), repo)]
    with ThreadPoolExecutor(_WORKERS, thread_name_prefix="cairn-packages") as pool:
        read = dict(zip(todo, pool.map(lambda repo: _read_repo(client, repo), todo), strict=True))
    found: list[RepoPackages] = []
    unread = 0
    for repo in repos:
        old, new = kept.get(repo.name.lower()), read.get(repo)
        if new is None:  # not due, or left for later: an old record beats none
            if old is None or not _current(old, repo):
                unread += 1
            if old is not None:
                found.append(old)
        elif new.failed and old is not None:  # a failed read never loses what was known
            found.append(old.model_copy(update={"failed": True}))
        else:
            found.append(new)
    return PackageIndex(
        version=INDEX_VERSION,
        org=org,
        host=host,
        built=now().isoformat(timespec="seconds"),
        ms=round((time.perf_counter() - started) * 1000, 1),
        repos=tuple(found),
        reread=sum(1 for record in read.values() if record is not None),
        unread=unread,
    )


def _current(record: RepoPackages | None, repo: RepoInfo) -> bool:
    return (
        record is not None
        and not record.failed
        and record.pushed == repo.pushed
        and record.branch == repo.default_branch
    )


def _read_repo(client: GitHub, repo: RepoInfo) -> RepoPackages | None:
    """A repo's packages, or None when the API budget runs too low to read it now. A rejected
    token stops the whole read (the caller then reads the token again)."""
    if _low(client):
        return None
    try:
        paths, _ = client.tree(repo.name, repo.default_branch)
    except CairnError as exc:
        _raise_if_auth(exc)
        return repo_packages(repo, [], failed=True)
    texts: list[tuple[str, str]] = []
    failed = False
    for path in package_manifests(paths):
        if _low(client):  # checked before every request: 16 workers read at once
            return None
        try:
            text = client.read_file(repo.name, path)
        except CairnError as exc:
            _raise_if_auth(exc)
            failed = True
            continue
        if text:
            texts.append((path, text))
    return repo_packages(repo, texts, failed=failed)


def package_manifests(paths: Sequence[str]) -> list[str]:
    """The manifests of a repo's own projects: not examples, fixtures or test data, and only
    paths that print as one plain line (git allows newlines in a folder's name)."""
    own = [p for p in paths if not _EXAMPLE.search(p) and clean_inline(p, len(p) + 1) == p]
    return manifests(own, MANIFESTS_PER_REPO)


def _low(client: GitHub) -> bool:
    left = client.remaining()
    return left is not None and left < RESERVE


def _raise_if_auth(exc: CairnError) -> None:
    if "rejected the token" in str(exc):
        raise exc


def repo_packages(
    repo: RepoInfo, texts: Sequence[tuple[str, str]], *, failed: bool = False
) -> RepoPackages:
    defines: dict[str, Defined] = {}
    uses: dict[tuple[str, str], Used] = {}
    for path, text in texts:
        own, used = parse_manifest(path, text)
        if _private(path, text):
            own = set()  # never published: no other repo can depend on it by name
        about = manifest_description(path, text)
        for name in sorted(own):
            if PACKAGE_NAME.fullmatch(name):
                defines.setdefault(name.lower(), Defined(name=name, path=path, description=about))
        for name in sorted(used):
            if PACKAGE_NAME.fullmatch(name):
                uses.setdefault((name.lower(), path), Used(name=name, path=path))
    return RepoPackages(
        repo=repo.name,
        pushed=repo.pushed,
        branch=repo.default_branch,
        fork=repo.fork,
        description=clean_inline(repo.description, _DESCRIPTION),
        defines=tuple(defines.values()),
        # A monorepo's packages using one another are its own business, not the org's.
        uses=tuple(u for (name, _), u in uses.items() if name not in defines),
        failed=failed,
    )


def _private(path: str, text: str) -> bool:
    return (
        path.rsplit("/", 1)[-1] == "package.json"
        and (parse_json(text) or {}).get("private") is True
    )


def manifest_description(path: str, text: str) -> str:
    """What a manifest says its package is for (package.json, pyproject.toml, Cargo.toml)."""
    name = path.rsplit("/", 1)[-1]
    value: object = None
    if name == "package.json":
        value = (parse_json(text) or {}).get("description")
    elif name == "pyproject.toml":
        data = parse_toml(text)
        value = dig(data, "project", "description") or dig(data, "tool", "poetry", "description")
    elif name == "Cargo.toml":
        value = dig(parse_toml(text), "package", "description")
    return clean_inline(value, _DESCRIPTION) if isinstance(value, str) else ""


def org_packages(index: PackageIndex) -> tuple[OrgPackage, ...]:
    """The packages one repo of the org defines and others use (or named under the org), most
    used first. A name several repos define is a template's (`cdk-app`), not a library."""
    homes: dict[str, dict[str, tuple[RepoPackages, Defined]]] = {}
    for record in index.repos:
        for package in record.defines:
            homes.setdefault(_key(package.name), {}).setdefault(record.repo, (record, package))
    repos = {record.repo.lower(): record for record in index.repos}
    users: dict[str, dict[str, list[str]]] = {}
    spellings: dict[str, Counter[str]] = {}
    for record in index.repos:
        for use in record.uses:
            key = _key(use.name)
            home = _home(homes.get(key, {}), index.org, index.host)
            if home is not None and home[0].repo == record.repo:
                continue  # an example inside the library's own repo
            if home is None and not under_org(use.name.lower(), index.org, index.host):
                continue
            users.setdefault(key, {}).setdefault(record.repo, []).append(use.path)
            spellings.setdefault(key, Counter())[use.name] += 1
    found = []
    for key, by_repo in users.items():
        home = _home(homes.get(key, {}), index.org, index.host)
        if home is None:
            owner = _go_repo(spellings[key].most_common(1)[0][0], index.host)
            record = repos.get(owner.lower()) if owner else None
            name, where, path = spellings[key].most_common(1)[0][0], record, ""
        else:
            name, where, path = home[1].name, home[0], home[1].path
        # The repo's own description fits only a package at its root, not one of its parts.
        root = "/" not in path if path else _key(name).count("/") == 2  # host/owner/repo
        description = (home[1].description if home else "") or (
            where.description if where and root else ""
        )
        found.append(
            OrgPackage(
                name=name,
                home=where.repo if where else "",
                path=path,
                description=description,
                users=tuple((repo, tuple(paths)) for repo, paths in by_repo.items()),
            )
        )
    return tuple(sorted(found, key=lambda p: (-len(p.users), p.name.lower())))


def _key(name: str) -> str:
    """One key for every major version of a Go module (hcl and hcl/v2 are one library)."""
    key = name.lower()
    return _GO_MAJOR.sub("", key) if key.startswith("go:") else key


def _home(
    found: dict[str, tuple[RepoPackages, Defined]], org: str, host: str
) -> tuple[RepoPackages, Defined] | None:
    """The one repo that defines a package: the original over forks of it. A fork alone is
    the home only of a name under the org (the org's own copy of a library), not of the
    upstream name it still declares. A Go module under another owner's path is that owner's,
    whatever repo holds a copy of it."""
    if not found or _foreign(next(iter(found.values()))[1].name, org, host):
        return None
    originals = [entry for entry in found.values() if not entry[0].fork]
    if len(originals) == 1:
        return originals[0]
    if originals or len(found) != 1:
        return None
    fork = next(iter(found.values()))
    return fork if under_org(fork[1].name.lower(), org, host) else None


def _foreign(name: str, org: str, host: str) -> bool:
    """Whether a Go module path names another owner on the org's host."""
    owner = _go_repo(name, host).partition("/")[0]
    return bool(owner) and owner.lower() != org.lower()


def _go_repo(name: str, host: str) -> str:
    """owner/name of the repo a Go module path lives in (`go:github.com/acme/kit/log`)."""
    ecosystem, _, path = name.partition(":")
    parts = path.split("/")
    if ecosystem != "go" or len(parts) < 3 or parts[0].lower() != host.lower():
        return ""
    return f"{parts[1]}/{parts[2]}"


def find_packages(packages: Sequence[OrgPackage], name: str) -> list[OrgPackage]:
    """The packages `name` means: an exact name (with or without its ecosystem), else those it
    ends, else those containing it."""
    wanted = name.strip().lower()
    if not wanted:
        return []
    if wanted.partition(":")[0] in ECOSYSTEMS:  # npm:acme-client, not python:acme-client
        exact = [p for p in packages if _key(p.name) == _key(wanted)]
        if exact:
            return exact
    for match in (
        lambda p: plain_name(p.name) == plain_name(wanted),
        lambda p: plain_name(p.name).endswith(("/" + wanted, "-" + wanted, "." + wanted)),
        lambda p: wanted in p.name.lower(),
    ):
        chosen = [p for p in packages if match(p)]
        if chosen:
            return chosen
    return []


def _bare(name: str) -> str:
    return name.partition(":")[2] or name


def plain_name(name: str) -> str:
    """A name compared as an agent might write it: no ecosystem, no Go major version."""
    ecosystem, _, bare = name.lower().partition(":")
    return _GO_MAJOR.sub("", bare if bare and ecosystem in ECOSYSTEMS else name.lower())


def import_name(name: str) -> str:
    """What code that uses the package writes to import it, for a code search."""
    ecosystem, _, bare = name.partition(":")
    if ecosystem == "go":
        return bare
    if ecosystem in ("python", "cargo"):
        return bare.replace("-", "_")
    if ecosystem == "maven":
        return bare.split(":", 1)[0]
    return bare


@dataclass(frozen=True)
class UsageFile:
    repo: str
    path: str
    fragment: str


def usage_files(client: GitHub, org: str, package: OrgPackage) -> tuple[UsageFile, ...]:
    """Code in the org that imports the package (one code search): manifests, lockfiles,
    vendored copies and the package's own repo left out, tests last."""
    page = client.search_code(f'"{import_name(package.name)}" org:{org}', per_page=30)
    found = [
        hit
        for hit in page.hits
        if hit.repo.split("/", 1)[0].lower() == org.lower()
        and hit.repo.lower() != package.home.lower()
        and not MANIFEST.search(hit.path)
        and not _LOCKFILE.search(hit.path)
        and weight(hit.path) >= _CODE  # code and tests, not docs or data
    ]
    found.sort(key=lambda hit: -weight(hit.path))  # stable: GitHub's order within a weight
    return tuple(
        UsageFile(
            repo=hit.repo,
            path=clean_inline(hit.path, 300),
            fragment=clean_inline(redact(" … ".join(hit.fragments)), _FRAGMENT),
        )
        for hit in found[:_FILES_SHOWN]
    )


def render_packages(
    index: PackageIndex,
    packages: Sequence[OrgPackage],
    *,
    query: str = "",
    limit: int = LIST_LIMIT,
) -> str:
    """The org's packages as an agent reads them: one line each, most used first."""
    words = query.lower().split()
    chosen = [p for p in packages if all(word in _haystack(p) for word in words)]
    matching = f" {len(chosen)} match {clean_inline(query, 60)!r}." if words else ""
    lines = [
        f"The own packages of {index.org} ({index.host}): the {len(packages)} libraries its "
        f"{len(index.repos)} active repos use from one another, most used first (by how many "
        f"repos), read {index.built[:10]}.{matching} Pass a name for where one is defined, "
        "every repo using it, and code that calls it."
    ]
    lines += [_line(p) for p in chosen[:limit]]
    if len(chosen) > limit:
        lines.append(f"… {len(chosen) - limit} more: pass a query (words in the name or purpose).")
    if not chosen and words:
        lines.append("None match: try one word, or no query for the most used.")
    lines += _gaps(index)
    return "\n".join(lines)


def render_package(
    index: PackageIndex, package: OrgPackage, files: Sequence[UsageFile] | str
) -> str:
    """One package: where it is defined, who uses it, and code that calls it (or why that code
    search failed)."""
    where = (
        f"defined in {package.home}/{package.path}"
        if package.path
        else (
            f"lives in {package.home}"
            if package.home
            else "defined by no single active repo (none read, or several)"
        )
    )
    about = f" {package.description}" if package.description else ""
    lines = [f"{_bare(package.name)} ({_ecosystem(package.name)}): {where}.{about}"]
    shown = package.users[:_USERS_SHOWN]
    lines.append(
        f"Used by {len(package.users)} active repos (latest push first): "
        + ", ".join(_user(repo, paths) for repo, paths in shown)
        + (
            f", and {len(package.users) - len(shown)} more"
            if len(package.users) > len(shown)
            else ""
        )
    )
    if isinstance(files, str):
        lines.append(f"(No code search: {files})")
    elif files:
        lines.append("Code that uses it (read one with read_org_file):")
        lines += [f"- {f.repo}/{f.path}: {f.fragment}".rstrip(": ") for f in files]
    else:
        lines.append("Code search found no file importing it outside its own repo.")
    lines += _gaps(index)
    return "\n".join(lines)


def _user(repo: str, paths: Sequence[str]) -> str:
    """A repo using a package, with the folders of a monorepo's projects that do."""
    name = repo.partition("/")[2] or repo
    if all("/" not in path for path in paths):
        return name
    return f"{name} ({', '.join(path.rpartition('/')[0] or '.' for path in paths)})"


def render_choices(packages: Sequence[OrgPackage], name: str) -> str:
    if not packages:
        return (
            f"No package of the org is called {clean_inline(name, 60)!r}: list them with no name."
        )
    names = ", ".join(f"{_bare(p.name)} ({_ecosystem(p.name)})" for p in packages[:LIST_LIMIT])
    return f"{clean_inline(name, 60)!r} could be any of these; pass the full name: {names}"


def _line(package: OrgPackage) -> str:
    folder = package.path.rpartition("/")[0]
    where = f"{package.home}/{folder}" if folder else package.home
    home = f" · in {where}" if where else ""
    about = f" — {package.description}" if package.description else ""
    return (
        f"- {_bare(package.name)} ({_ecosystem(package.name)}) · {len(package.users)} repos"
        f"{home}{about}"
    )


def _ecosystem(name: str) -> str:
    ecosystem = name.partition(":")[0]
    return ECOSYSTEMS.get(ecosystem, ecosystem)


def _haystack(package: OrgPackage) -> str:
    return f"{package.name} {package.home} {package.path} {package.description}".lower()


def _gaps(index: PackageIndex) -> list[str]:
    notes = []
    failed = sum(1 for record in index.repos if record.failed)
    if index.unread:
        notes.append(
            f"({index.unread} repos aren't read yet: GitHub's API budget ran low. A later call "
            "reads them.)"
        )
    if failed:
        notes.append(f"({failed} repos couldn't be read fully; a later call retries them.)")
    return notes


def needs_build(index: PackageIndex, now: datetime) -> bool:
    """A day old, or left part-read: read the org (only what changed) again."""
    if older_than(index.built, now, MAX_AGE):
        return True
    failed = sum(1 for record in index.repos if record.failed)
    return index.unread > 0 or failed * 10 > len(index.repos)


def load_index(path: Path) -> PackageIndex | None:
    try:
        return PackageIndex.model_validate_json(path.read_bytes())
    except (OSError, ValueError, ValidationError):
        return None


def save_index(path: Path, index: PackageIndex) -> None:
    save_cache(path, index.model_dump_json())
