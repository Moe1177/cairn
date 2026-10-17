"""An org's stack: the languages, datastores, frameworks, auth, test and deploy tools its active
repos use, the libraries they depend on, and the org's own packages they share.

An agent writing code for the org should build with what the org builds with: its database, its
queue, its test runner, its deploy tool, its own shared packages. The profile says what those
are, and how many of the active repos use each, in a few lines.

Read over the API from the most recently pushed repos (where today's conventions live): a few
listing pages, one git tree per repo, and a few manifests each. About 15 s for 200 repos, then
cached for a week.
"""

import os
import re
import time
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import Field, ValidationError

from cairn.detectors import jvm
from cairn.detectors.manifests import (
    dig,
    normalize_py,
    npm_dependencies,
    parse_go_mod,
    parse_json,
    parse_toml,
    project_name,
    pyproject_requirement_names,
    requirements_names,
)
from cairn.errors import CairnError
from cairn.model.graph import Frozen
from cairn.org.similar import weight
from cairn.org.tech import CATEGORIES, CATEGORY, repo_techs
from cairn.remote.host import CodeHost, RepoInfo

SAMPLE = 200  # repos read: the most recently pushed ones
MANIFESTS_PER_REPO = 3  # the shallowest: a repo's own, not its examples' or fixtures'
MAX_AGE = timedelta(days=7)
_WORKERS = 16
_MAX_PAGES = 20  # an org whose recent repos are nearly all archived stops here
_LIST_BATCH = 10  # listing pages read at once
_TOP_TECHS = 8
_TOP_LIBRARIES = 12
_TOP_OWN = 10
_TOP_TOPICS = 12

MANIFEST = re.compile(
    r"(?:^|/)(?:package\.json|requirements\.txt|pyproject\.toml|go\.mod|pom\.xml|"
    r"build\.gradle(?:\.kts)?|Cargo\.toml|Gemfile)$"
)
_BUILT = re.compile(r"(?:^|/)(?:dist|build|out|target|\.next)/")
# What a package name can be in any ecosystem: a manifest's keys are free text, and these are
# shown to an agent, so a "dependency" that is a sentence is dropped, not passed on.
PACKAGE_NAME = re.compile(r"^[a-z]{2,6}:[A-Za-z0-9@][\w@/.+:~-]{0,99}$", re.ASCII)
# Spaces and tabs only, never `\s`: it crosses lines, and backtracks quadratically on a file of
# blank lines (manifests are other people's text).
_GO_INDIRECT = re.compile(r"^[ \t]*(?:require[ \t]+)?(\S+)[ \t]+\S+[ \t]*//[ \t]*indirect", re.M)
_GEM = re.compile(r"""^[ \t]*gem[ \t]+["']([A-Za-z0-9._-]+)["']""", re.M)
_CARGO_SECTIONS = ("dependencies", "dev-dependencies", "build-dependencies")
# Build and lint tooling: in every repo, and no help in choosing what to search for.
_TOOLING = re.compile(
    r"^(?:npm:(?:@types/.*|typescript|ts-node|ts-jest|tslib|eslint.*|@eslint/.*|"
    r"@typescript-eslint/.*|prettier.*|husky|lint-staged|nodemon|rimraf|source-map-support|"
    r"@babel/.*|babel-.*|webpack.*|concurrently|cross-env|esbuild|@vitejs/.*)"
    r"|python:(?:pip|setuptools|wheel|black|flake8|isort|mypy|ruff|pylint|pre-commit|"
    r"pytest-.*|coverage|tox|bandit|types-.*)"
    r"|go:golang\.org/x/.*"
    r"|maven:org\.apache\.maven\.plugins:.*)$"
)
ECOSYSTEMS = {
    "python": "Python",
    "npm": "npm",
    "go": "Go",
    "maven": "JVM",
    "cargo": "Rust",
    "ruby": "Ruby",
}


class Count(Frozen):
    name: str
    repos: int


class OwnPackage(Frozen):
    name: str  # ecosystem:name
    home: str = ""  # owner/name of the repo that defines it, when one was read
    used_by: int


class OrgProfile(Frozen):
    org: str
    host: str
    built: str  # ISO time, UTC
    sampled: int  # repos read
    ms: float
    failed: int = 0  # repos whose tree or manifests couldn't be read
    languages: tuple[Count, ...] = ()
    techs: dict[str, tuple[Count, ...]] = Field(default_factory=dict)  # category -> techs
    libraries: dict[str, tuple[Count, ...]] = Field(default_factory=dict)  # ecosystem -> top
    own: tuple[OwnPackage, ...] = ()
    topics: tuple[Count, ...] = ()


@dataclass(frozen=True)
class RepoStack:
    repo: RepoInfo
    uses: frozenset[str]  # ecosystem:name
    defines: frozenset[str]
    techs: frozenset[str]


def build_profile(
    client: CodeHost,
    org: str,
    host: str = "github.com",
    *,
    sample: int = SAMPLE,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> OrgProfile:
    started = time.perf_counter()
    repos = active_repos(client, org, sample)
    if not repos:
        raise CairnError(f"{org} has no repos cairn can read (or none that aren't archived)")
    with ThreadPoolExecutor(_WORKERS, thread_name_prefix="cairn-profile") as pool:
        trees = list(pool.map(lambda repo: _tree(client, repo), repos))
        wanted = [
            (index, path) for index, paths in enumerate(trees) if paths for path in manifests(paths)
        ]
        texts = list(pool.map(lambda item: _read(client, repos[item[0]], item[1]), wanted))
    found: dict[int, list[tuple[str, str | None]]] = {}
    for (index, path), text in zip(wanted, texts, strict=True):
        found.setdefault(index, []).append((path, text))
    stacks, failed = [], 0
    for index, repo in enumerate(repos):
        read = found.get(index, [])
        if trees[index] is None or any(text is None for _, text in read):
            failed += 1
        if trees[index] is not None:
            stacks.append(repo_stack(repo, trees[index] or (), read))
    if not stacks:
        raise CairnError(f"couldn't read any of {org}'s repos")
    ms = (time.perf_counter() - started) * 1000
    return summarize(org, host, stacks, ms=ms, failed=failed, built=now())


def active_repos(
    client: CodeHost, org: str, sample: int, *, max_pages: int = _MAX_PAGES
) -> list[RepoInfo]:
    """The `sample` most recently pushed repos that aren't archived (forks count)."""
    batch = min(-(-sample // 100) + 1, _LIST_BATCH)
    repos: dict[str, RepoInfo] = {}
    with ThreadPoolExecutor(batch, thread_name_prefix="cairn-list") as pool:
        for first in range(1, max_pages + 1, batch):
            pages = list(
                pool.map(lambda n: client.list_repos(org, page=n), range(first, first + batch))
            )
            for page in pages:
                for repo in page:
                    if not repo.archived:
                        repos.setdefault(repo.name.lower(), repo)
            if len(repos) >= sample or any(len(page) < 100 for page in pages):
                break
    return list(repos.values())[:sample]


def manifests(paths: Iterable[str], limit: int = MANIFESTS_PER_REPO) -> list[str]:
    """The manifests worth reading: a repo's own (shallowest first), not vendored or built."""
    found = [
        path
        for path in paths
        if MANIFEST.search(path) and weight(path) > 0 and not _BUILT.search(path)
    ]
    return sorted(found, key=lambda path: (path.count("/"), path))[:limit]


def parse_manifest(path: str, text: str) -> tuple[set[str], set[str]]:
    """(packages a manifest defines, packages it uses), each `ecosystem:name`."""
    name = path.rsplit("/", 1)[-1]
    if name == "package.json":
        data = parse_json(text) or {}
        own = data.get("name")
        defines = {f"npm:{own}"} if isinstance(own, str) and own.strip() else set()
        return defines, {f"npm:{dep}" for dep in npm_dependencies(data)}
    if name == "requirements.txt":
        return set(), {f"python:{normalize_py(dep)}" for dep in requirements_names(text)}
    if name == "pyproject.toml":
        data = parse_toml(text)
        own = project_name(data)
        defines = {f"python:{normalize_py(own)}"} if own else set()
        return defines, {f"python:{normalize_py(d)}" for d in pyproject_requirement_names(data)}
    if name == "go.mod":
        module, requires = parse_go_mod(text)
        direct = set(requires) - set(_GO_INDIRECT.findall(text))  # what the code imports
        return ({f"go:{module}"} if module else set()), {f"go:{req}" for req in direct}
    if name == "pom.xml":
        own, deps = jvm.maven(text)
        return ({own} if own else set()), set(deps)
    if name.startswith("build.gradle"):
        folder = path.rpartition("/")[0]
        own, deps = jvm.gradle(text, folder=folder, settings=None, inherited_group=None)
        return ({own} if own else set()), set(deps)
    if name == "Cargo.toml":
        data = parse_toml(text) or {}
        own = dig(data, "package", "name")
        uses = {
            f"cargo:{dep}"
            for section in _CARGO_SECTIONS
            if isinstance(data.get(section), dict)
            for dep in data[section]
        }
        return ({f"cargo:{own}"} if isinstance(own, str) else set()), uses
    if name == "Gemfile":
        return set(), {f"ruby:{gem}" for gem in _GEM.findall(text)}
    return set(), set()


def repo_stack(
    repo: RepoInfo, paths: Sequence[str], read: Iterable[tuple[str, str | None]]
) -> RepoStack:
    defines: set[str] = set()
    uses: set[str] = set()
    for path, text in read:
        if text:
            own, used = parse_manifest(path, text)
            defines |= {name for name in own if PACKAGE_NAME.fullmatch(name)}
            uses |= {name for name in used if PACKAGE_NAME.fullmatch(name)}
    kept = [path for path in paths if weight(path) > 0 and not _BUILT.search(path)]
    techs = repo_techs(uses, repo.topics, kept)
    return RepoStack(repo, frozenset(uses - defines), frozenset(defines), frozenset(techs))


def summarize(
    org: str,
    host: str,
    stacks: Sequence[RepoStack],
    *,
    ms: float = 0.0,
    failed: int = 0,
    built: datetime | None = None,
) -> OrgProfile:
    floor = 2 if len(stacks) >= 20 else 1  # one repo of many is an accident, not a convention
    languages = Counter(s.repo.language for s in stacks if s.repo.language)
    techs = Counter(tech for s in stacks for tech in s.techs)
    by_category: dict[str, tuple[Count, ...]] = {}
    for category in CATEGORIES:
        counts = [(n, c) for n, c in techs.most_common() if CATEGORY[n] == category and c >= floor]
        if counts:
            by_category[category] = _counts(counts[:_TOP_TECHS])
    libraries = Counter(p for s in stacks for p in s.uses if not _TOOLING.match(p.lower()))
    common = max(floor, -(-len(stacks) * 2 // 100))  # a library 1 repo in 50 uses isn't the stack
    by_ecosystem: dict[str, tuple[Count, ...]] = {}
    for ecosystem in ECOSYSTEMS:
        counts = [
            (p.split(":", 1)[1], c)
            for p, c in libraries.most_common()
            if p.startswith(f"{ecosystem}:") and c >= common
        ]
        if counts:
            by_ecosystem[ecosystem] = _counts(counts[:_TOP_LIBRARIES])
    topics = Counter(t for s in stacks for t in s.repo.topics)
    return OrgProfile(
        org=org,
        host=host,
        built=(built or datetime.now(UTC)).isoformat(timespec="seconds"),
        sampled=len(stacks),
        ms=round(ms, 1),
        failed=failed,
        languages=_counts([(n, c) for n, c in languages.most_common(8) if c >= floor]),
        techs=by_category,
        libraries=by_ecosystem,
        own=own_packages(org, host, stacks),
        topics=_counts([(t, c) for t, c in topics.most_common(_TOP_TOPICS) if c >= floor]),
    )


def own_packages(org: str, host: str, stacks: Sequence[RepoStack]) -> tuple[OwnPackage, ...]:
    """The org's packages its repos share: defined by one repo read and used by others, or
    named under the org (`@acme/...`, `github.com/acme/...`, `com.acme...`, `acme-...`)."""
    homes: dict[str, list[str]] = {}
    for stack in stacks:
        for package in stack.defines:
            homes.setdefault(package.lower(), []).append(stack.repo.name)
    users: Counter[str] = Counter()
    names: dict[str, str] = {}
    for stack in stacks:
        for package in stack.uses:
            key = package.lower()
            home = homes.get(key, [])
            # Defined by several repos read, the name is a template's (`cdk-app`), not a library.
            if (len(home) == 1 and home[0] != stack.repo.name) or under_org(key, org, host):
                users[key] += 1
                names.setdefault(key, package)
    ranked = sorted(users, key=lambda key: (-users[key], key))[:_TOP_OWN]
    return tuple(
        OwnPackage(
            name=names[key],
            home=homes[key][0] if len(homes.get(key, [])) == 1 else "",
            used_by=users[key],
        )
        for key in ranked
    )


def under_org(package: str, org: str, host: str) -> bool:
    """Whether a package's name puts it in the org. A Go module path names the org (on GitLab,
    a subgroup too); other ecosystems name only a top-level group, as npm scopes do."""
    ecosystem, _, name = package.partition(":")
    if ecosystem == "go":
        return name.startswith(f"{host.lower()}/{org.lower()}/")
    org = org.partition("/")[0].lower()
    if ecosystem == "npm":
        return name.startswith(f"@{org}/")
    if ecosystem == "maven":
        group = name.split(":", 1)[0]
        return org.replace("-", "") in group.split(".")
    if ecosystem in ("python", "cargo", "ruby"):
        return name.startswith((f"{org}-", f"{org}_"))
    return False


def _counts(pairs: Iterable[tuple[str, int]]) -> tuple[Count, ...]:
    return tuple(Count(name=name, repos=repos) for name, repos in pairs)


def _tree(client: CodeHost, repo: RepoInfo) -> tuple[str, ...] | None:
    try:
        return client.tree(repo.name, repo.default_branch)[0]
    except CairnError:
        return None


def _read(client: CodeHost, repo: RepoInfo, path: str) -> str | None:
    try:
        return client.read_file(repo.name, path) or ""
    except CairnError:
        return None


def render_profile(profile: OrgProfile) -> str:
    """The profile as an agent reads it: one line per kind of thing, most used first."""
    n = max(profile.sampled, 1)

    def share(counts: Iterable[Count]) -> str:
        return ", ".join(f"{c.name} {max(1, round(100 * c.repos / n))}%" for c in counts)

    built = profile.built[:10]
    lines = [
        f"The stack of {profile.org} ({profile.host}): what its {profile.sampled} most recently "
        f"pushed repos use (share of those repos), read {built}."
    ]
    if profile.languages:
        lines.append(f"Languages: {share(profile.languages)}")
    lines += [f"{c}: {share(profile.techs[c])}" for c in CATEGORIES if profile.techs.get(c)]
    lines += [
        f"{ECOSYSTEMS[e]} libraries: {share(profile.libraries[e])}"
        for e in ECOSYSTEMS
        if profile.libraries.get(e)
    ]
    if profile.own:
        own = "; ".join(
            f"{p.name.partition(':')[2] or p.name}"
            + (f" (from {p.home.rpartition('/')[2]}," if p.home else " (")
            + f" used by {p.used_by})"
            for p in profile.own
        )
        lines.append(f"The org's own packages: {own}")
    if profile.topics:
        lines.append(f"Topics: {', '.join(t.name for t in profile.topics)}")
    if profile.failed:
        lines.append(f"({profile.failed} repos couldn't be read fully.)")
    return "\n".join(lines)


def load_profile(path: Path) -> OrgProfile | None:
    try:
        return OrgProfile.model_validate_json(path.read_bytes())
    except (OSError, ValueError, ValidationError):
        return None


def save_profile(path: Path, profile: OrgProfile) -> None:
    save_cache(path, profile.model_dump_json(indent=1))


def save_cache(path: Path, text: str) -> None:
    """Write a cache file whole or not at all: a reader never sees half of one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(f".{os.getpid()}.tmp")
    temp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temp, path)


def is_stale(profile: OrgProfile, now: datetime) -> bool:
    return older_than(profile.built, now, MAX_AGE)


def older_than(built: str, now: datetime, age: timedelta) -> bool:
    """Whether a cache stamped `built` (ISO, UTC) is over `age` old, or isn't a stamp cairn
    wrote."""
    try:
        when = datetime.fromisoformat(built)
    except ValueError:
        return True
    if when.tzinfo is None or when > now:  # not one cairn wrote, or a clock gone wrong
        return True
    return now - when > age


def is_degraded(profile: OrgProfile) -> bool:
    """Whether over a tenth of the repos couldn't be read (a rate limit hit mid-build, say):
    such a profile is shown once, never cached for a week."""
    return profile.failed * 10 > profile.sampled + profile.failed
