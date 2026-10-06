"""The scan pipeline: discover repos, run detectors, match edges, apply overrides."""

import shutil
from collections import Counter
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import cairn.detectors as detector_registry
from cairn.config import CairnConfig
from cairn.detectors import IDENTITY_DETECTORS, LIVE_DETECTOR_IDS, LIVE_FILE_MATCHERS
from cairn.detectors.base import (
    Detector,
    DetectorContext,
    DetectorResult,
    KnownFiles,
    combine_results,
)
from cairn.detectors.identity import clean_aliases
from cairn.discover.files import DEFAULT_IGNORE_DIRS, safe_exists
from cairn.discover.git import GitInfo, forget_git_memo, git_refused, summary_is_stale
from cairn.discover.repos import RepoLocation, discover_repos
from cairn.errors import CairnError
from cairn.load import load_authored, load_config, load_relations
from cairn.match.matcher import RepoFacts, match_edges
from cairn.match.overrides import apply_overrides
from cairn.match.scoring import DEFAULT_TABLE_STOPLIST
from cairn.model.graph import Contracts, DetectorError, Repo, Workspace, unsafe_path
from cairn.model.overrides import Authored, Relations
from cairn.scan_cache import (
    CacheEntry,
    cache_key,
    from_cached,
    load_entry,
    load_git_memo,
    repo_state,
    save_entry,
    save_git_memo,
    to_cached,
)
from cairn.security.redact import redact

Run = tuple[DetectorResult, tuple[DetectorError, ...]]


SCAN_WORKERS = 8


@dataclass(frozen=True)
class ScanResult:
    workspace: Workspace
    authored: Mapping[str, Authored]
    relations: Relations
    config: CairnConfig
    warnings: tuple[str, ...]
    cached: tuple[str, ...] = ()


@dataclass(frozen=True)
class _RepoRead:
    identity: Run
    relation: Run
    cached: bool
    live_files: tuple[Path, ...] | None = None  # what the live detectors will look at


def scan_workspace(
    ws_root: Path, *, now: datetime | None = None, use_cache: bool = True
) -> ScanResult:
    root = ws_root.resolve()
    if not root.is_dir():
        raise CairnError(f"{ws_root} is not a directory")
    if safe_exists(root / ".git"):
        raise _inside_repo_error(root, root)
    config, relations, authored = load_config(root), load_relations(root), load_authored(root)
    locations = discover_repos(
        root,
        ignore_dirs=DEFAULT_IGNORE_DIRS | frozenset(config.ignore_dirs),
        max_depth=config.max_depth,
        ignore_repos=frozenset(relations.ignore_repos),
    )
    # A folder name git allows but a map can't hold safely (control characters) is skipped.
    skipped = [loc for loc in locations if unsafe_path(loc.rel_path(root))]
    locations = tuple(loc for loc in locations if loc not in skipped)
    enclosing = next((p for p in root.parents if safe_exists(p / ".git")), None)
    if not locations and enclosing is not None:
        raise _inside_repo_error(root, enclosing)
    if not use_cache:
        forget_git_memo()  # --full: ask git everything afresh (also clears a bad memo)
    elif locations:
        load_git_memo(root)
    # Per-repo work is mostly waiting on git subprocesses and disk: run it in parallel.
    with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as pool:
        states = list(pool.map(lambda loc: repo_state(loc.root), locations))
        gits = {loc.id: state[0] for loc, state in zip(locations, states, strict=True)}
        prints = {loc.id: state[1] for loc, state in zip(locations, states, strict=True)}
        read_list = list(
            pool.map(
                lambda loc: _read_repo(root, loc, config, gits[loc.id], prints[loc.id], use_cache),
                locations,
            )
        )
        reads = {loc.id: read for loc, read in zip(locations, read_list, strict=True)}
        aliases = {
            loc.id: _aliases_for(
                loc, reads[loc.id].identity[0], gits[loc.id], relations, authored, config
            )
            for loc in locations
        }
        table = build_alias_table(aliases)
        live = _detectors(live=True)
        # Live detectors need every repo's aliases, so they run after the reads: in the pool
        # too (each repo walks its files; the alias table is shared read-only).
        live_runs = list(
            pool.map(
                lambda loc: _run_all(live, _live_context(root, loc, config, table, reads[loc.id])),
                locations,
            )
        )
    lived = {loc.id: run for loc, run in zip(locations, live_runs, strict=True)}
    if locations:
        save_git_memo(root, (loc.root for loc in locations))
    repos = tuple(
        _build_repo(
            root,
            loc,
            reads[loc.id].identity,
            _merge(reads[loc.id].relation, lived[loc.id]),
            gits[loc.id],
            aliases[loc.id],
            _is_stale(loc, gits[loc.id], authored.get(loc.id), config),
        )
        for loc in locations
    )
    stop = DEFAULT_TABLE_STOPLIST | frozenset(t.lower() for t in config.stop_tables)
    edges = match_edges(
        [RepoFacts(r.id, r.path, r.contracts, r.aliases) for r in repos], stop_tables=stop
    )
    overridden = apply_overrides(edges, relations, authored, frozenset(r.id for r in repos))
    workspace = Workspace(
        workspace_root=root.as_posix(),
        generated_at=(now or datetime.now(UTC)).isoformat(timespec="seconds"),
        repos=repos,
        edges=overridden.edges,
    )
    cached = tuple(repo_id for repo_id, read in reads.items() if read.cached)
    unsafe = tuple(f"skipped {loc.root.name!r}: unusual characters in its path" for loc in skipped)
    warnings = (
        *_git_warning(locations),
        *_trust_warning(locations, prints),
        *_lineage_warning(repos),
        *unsafe,
        *overridden.warnings,
    )
    return ScanResult(workspace, authored, relations, config, warnings, cached)


def _lineage_warning(repos: Sequence[Repo]) -> list[str]:
    """Repos whose first commits git couldn't list in time: their copies aren't linked this
    time (nothing is cached, so the next scan tries again)."""
    failed = [r.id for r in repos if any(e.detector == "lineage" for e in r.detector_errors)]
    if not failed:
        return []
    return [
        f"couldn't read the first commit of {', '.join(failed)} in time: links between "
        "copies of one app may be missing; run `cairn refresh` again"
    ]


def _trust_warning(
    locations: Sequence[RepoLocation], prints: Mapping[str, str | None]
) -> tuple[str, ...]:
    """One warning naming the repos git refuses to read. Only repos whose `git status` failed
    are asked: HEAD can still come from the git memo when git has started refusing a repo."""
    refused = [
        loc
        for loc in locations
        if prints[loc.id] is None and safe_exists(loc.root / ".git") and git_refused(loc.root)
    ]
    if not refused:
        return ()
    names = ", ".join(loc.id for loc in refused[:5]) + (" ..." if len(refused) > 5 else "")
    example = refused[0].root.as_posix()
    return (
        f"git refuses {len(refused)} repo(s) owned by another user (dubious ownership): {names}. "
        f"cairn can't read their HEAD, remote or cache. Trust each one with "
        f"`git config --global --add safe.directory '{example}'` (`cairn doctor` lists them "
        "all).",
    )


def _git_warning(locations: Sequence[RepoLocation]) -> tuple[str, ...]:
    if locations and shutil.which("git") is None:
        return ("git not found on PATH: remotes, HEAD, staleness and the scan cache are off",)
    return ()


def _detectors(*, live: bool) -> tuple[Detector, ...]:
    # Looked up at call time so tests can monkeypatch the registry.
    return tuple(
        d for d in detector_registry.RELATION_DETECTORS if (d.id in LIVE_DETECTOR_IDS) == live
    )


def _read_repo(
    root: Path,
    loc: RepoLocation,
    config: CairnConfig,
    git: GitInfo,
    fingerprint: str | None,
    use_cache: bool,
) -> _RepoRead:
    """Identity + file-reading relation detectors, served from the cache when nothing changed."""
    key = cache_key(git.head_sha, fingerprint, config)
    entry = load_entry(root, loc.id, key) if key and use_cache else None
    if entry is not None:
        relation = (from_cached(entry.relation), entry.errors)
        return _RepoRead((from_cached(entry.identity), ()), relation, True, _known_live(loc, entry))
    ctx = DetectorContext(root, loc, config)  # one walk and one read per file for both
    identity = _run_all(IDENTITY_DETECTORS, ctx)
    relation = _run_all(_detectors(live=False), ctx)
    live = ctx.matching(LIVE_FILE_MATCHERS)
    # A failed read (a file locked by antivirus, say) may be transient: never pin it.
    if key and not identity[1] and not relation[1]:
        entry = CacheEntry(
            key=key,
            identity=to_cached(identity[0]),
            relation=to_cached(relation[0]),
            live_files=tuple(path.relative_to(loc.root).as_posix() for path in live),
            live_dirs=ctx.folder_stamps(),
        )
        save_entry(root, loc.id, entry)
    return _RepoRead(identity, relation, False, live)


def _known_live(loc: RepoLocation, entry: CacheEntry) -> tuple[Path, ...] | None:
    """The live detectors' files from the cache, if no walked folder gained or lost a file.

    The cache key (HEAD + `git status`) can't see files git ignores, which cairn still reads
    (a git-ignored `scripts/dev.sh`); a folder's mtime moves when one appears or goes.
    """
    if entry.live_files is None or entry.live_dirs is None:
        return None
    for rel, mtime in entry.live_dirs:
        try:
            if (loc.root / rel).stat().st_mtime_ns != mtime:
                return None
        except OSError:
            return None
    return tuple(loc.root / rel for rel in entry.live_files)


def _live_context(
    root: Path, loc: RepoLocation, config: CairnConfig, table: Mapping[str, str], read: _RepoRead
) -> DetectorContext:
    """The live detectors' context: walk-free when the read already knows their files."""
    known = None if read.live_files is None else KnownFiles(LIVE_FILE_MATCHERS, read.live_files)
    return DetectorContext(root, loc, config, table, known)


def _is_stale(
    loc: RepoLocation, git: GitInfo, authored: Authored | None, config: CairnConfig
) -> bool:
    """Only asks git when an authored summary was written at a different commit."""
    if not (authored and authored.summary and authored.summary_sha and git.head_sha):
        return False
    sha, head = authored.summary_sha, git.head_sha
    if head.startswith(sha) or sha.startswith(head):
        return False
    return summary_is_stale(loc.root, sha, config.stale_file_threshold)


def _merge(a: Run, b: Run) -> Run:
    return combine_results([a[0], b[0]]), (*a[1], *b[1])


def _inside_repo_error(root: Path, repo: Path) -> CairnError:
    return CairnError(
        f"{root} is inside the git repository {repo}. Run cairn from the folder that "
        f"contains your repos (for example {repo.parent}), so it never writes into a repo."
    )


def build_alias_table(aliases: Mapping[str, Sequence[str]]) -> dict[str, str]:
    ids = {repo_id.lower(): repo_id for repo_id in aliases}
    owners = Counter(a for names in aliases.values() for a in {n.lower() for n in names})
    table = dict(ids)
    for repo_id, names in aliases.items():
        for name in names:
            alias = name.lower()
            if alias not in ids and owners[alias] == 1:
                table[alias] = repo_id
    return table


def _run_all(detectors: Sequence[Detector], ctx: DetectorContext) -> Run:
    results: list[DetectorResult] = []
    errors: list[DetectorError] = []
    for detector in detectors:
        try:
            results.append(detector.run(ctx))
        except Exception as exc:  # a detector bug must never abort a scan
            message = redact(f"{type(exc).__name__}: {exc}")[:300]
            errors.append(DetectorError(detector=detector.id, message=message))
    return combine_results(results), tuple(errors)


def _aliases_for(
    loc: RepoLocation,
    identity: DetectorResult,
    git: GitInfo,
    relations: Relations,
    authored: Mapping[str, Authored],
    config: CairnConfig,
) -> tuple[str, ...]:
    detected = [*identity.aliases]
    if git.remote:
        detected.append(git.remote.rsplit("/", 1)[-1])
    cleaned = clean_aliases(detected, loc.id, frozenset(config.stop_aliases))
    user = [
        *relations.aliases.get(loc.id, ()),
        *(authored[loc.id].aliases if loc.id in authored else ()),
    ]
    seen = {a.lower() for a in cleaned}
    extra = [u.strip().lower() for u in user if u.strip() and u.strip().lower() not in seen]
    return tuple(dict.fromkeys((*cleaned, *extra)))


def _build_repo(
    ws_root: Path,
    loc: RepoLocation,
    identity: Run,
    relation: Run,
    git: GitInfo,
    aliases: tuple[str, ...],
    summary_stale: bool = False,
) -> Repo:
    first, first_errors = identity
    second, second_errors = relation
    return Repo(
        id=loc.id,
        path=loc.rel_path(ws_root),
        app_roots=tuple(p.relative_to(ws_root).as_posix() for p in loc.app_roots),
        aliases=aliases,
        remote=git.remote,
        stack=first.stack,
        head_sha=git.head_sha,
        dirty=git.dirty,
        commands=first.commands,
        layout=first.layout,
        readme_excerpt=first.readme_excerpt,
        summary_stale=summary_stale,
        packages=tuple(
            p.model_copy(update={"path": f"{loc.rel_path(ws_root)}/{p.path}"})
            for p in second.packages
        ),
        contracts=Contracts(exposes=second.exposes, consumes=second.consumes),
        detector_errors=(*first_errors, *second_errors),
    )
