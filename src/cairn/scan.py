"""The scan pipeline: discover repos, run detectors, match edges, apply overrides."""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cairn.config import CairnConfig
from cairn.detectors import IDENTITY_DETECTORS, RELATION_DETECTORS
from cairn.detectors.base import Detector, DetectorContext, DetectorResult, combine_results
from cairn.detectors.identity import clean_aliases
from cairn.discover.files import DEFAULT_IGNORE_DIRS
from cairn.discover.git import GitInfo, git_info
from cairn.discover.repos import RepoLocation, discover_repos
from cairn.errors import CairnError
from cairn.load import load_authored, load_config, load_relations
from cairn.match.matcher import RepoFacts, match_edges
from cairn.match.overrides import apply_overrides
from cairn.match.scoring import DEFAULT_TABLE_STOPLIST
from cairn.model.graph import Contracts, DetectorError, Repo, Workspace
from cairn.model.overrides import Authored, Relations
from cairn.security.redact import redact

Run = tuple[DetectorResult, tuple[DetectorError, ...]]


@dataclass(frozen=True)
class ScanResult:
    workspace: Workspace
    authored: Mapping[str, Authored]
    relations: Relations
    config: CairnConfig
    warnings: tuple[str, ...]


def scan_workspace(ws_root: Path, *, now: datetime | None = None) -> ScanResult:
    root = ws_root.resolve()
    if not root.is_dir():
        raise CairnError(f"{ws_root} is not a directory")
    config, relations, authored = load_config(root), load_relations(root), load_authored(root)
    locations = discover_repos(
        root,
        ignore_dirs=DEFAULT_IGNORE_DIRS | frozenset(config.ignore_dirs),
        max_depth=config.max_depth,
        ignore_repos=frozenset(relations.ignore_repos),
    )
    gits = {loc.id: git_info(loc.root) for loc in locations}
    identity = {
        loc.id: _run_all(IDENTITY_DETECTORS, DetectorContext(root, loc, config))
        for loc in locations
    }
    aliases = {
        loc.id: _aliases_for(loc, identity[loc.id][0], gits[loc.id], relations, authored, config)
        for loc in locations
    }
    table = build_alias_table(aliases)
    relation = {
        loc.id: _run_all(RELATION_DETECTORS, DetectorContext(root, loc, config, table))
        for loc in locations
    }
    repos = tuple(
        _build_repo(root, loc, identity[loc.id], relation[loc.id], gits[loc.id], aliases[loc.id])
        for loc in locations
    )
    stop = DEFAULT_TABLE_STOPLIST | frozenset(t.lower() for t in config.stop_tables)
    edges = match_edges([RepoFacts(r.id, r.path, r.contracts) for r in repos], stop_tables=stop)
    overridden = apply_overrides(edges, relations, authored, frozenset(r.id for r in repos))
    workspace = Workspace(
        workspace_root=root.as_posix(),
        generated_at=(now or datetime.now(UTC)).isoformat(timespec="seconds"),
        repos=repos,
        edges=overridden.edges,
    )
    return ScanResult(workspace, authored, relations, config, overridden.warnings)


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
        contracts=Contracts(exposes=second.exposes, consumes=second.consumes),
        detector_errors=(*first_errors, *second_errors),
    )
