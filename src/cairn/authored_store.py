"""Write harness/human-authored content (.cairn/authored/<repo>.yaml) without clobbering it."""

import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Literal

import yaml

from cairn.errors import CairnError, CairnInputError
from cairn.load import load_authored
from cairn.model.graph import SYMMETRIC_TYPES, Edge, EdgeType
from cairn.model.overrides import Authored
from cairn.paths import authored_dir
from cairn.resolve import resolve_repo
from cairn.store.atomic import atomic_write_text
from cairn.store.workspace_store import load_workspace

_KEY = re.compile(r"^(?P<source>.+?)->(?P<target>.+):(?P<type>[a-z_]+)$")
Review = Literal["confirmed", "rejected"]


def parse_edge_key(key: str) -> tuple[str, str, EdgeType]:
    match = _KEY.match(key.strip())
    if not match:
        raise CairnInputError(key, "expected an edge key like 'source->target:shares_db'")
    try:
        edge_type = EdgeType(match["type"])
    except ValueError as exc:
        raise CairnInputError(key, f"unknown edge type '{match['type']}'") from exc
    return match["source"], match["target"], edge_type


def save_authored(ws_root: Path, repo_id: str, authored: Authored) -> Path:
    path = authored_dir(ws_root) / f"{repo_id}.yaml"
    data = authored.model_dump(mode="json", exclude_defaults=True)
    atomic_write_text(path, yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    return path


def annotate_edge(ws_root: Path, key: str, *, review: Review | None, why: str | None) -> Path:
    """Record a review and/or explanation for an edge, keeping every other authored field.

    The decision is stored under the edge's canonical key (its current direction), and any
    stale copy under the reversed key is removed, so the newest decision always wins.
    An edge the user rejected earlier is no longer in the map but can still be re-decided.
    """
    _, _, edge_type = parse_edge_key(key)
    workspace = load_workspace(ws_root)
    if workspace is None:
        raise CairnError("No map found. Run `cairn scan` first.")
    authored = load_authored(ws_root)
    variants = _key_variants(key, edge_type)
    canonical = _canonical_key(variants, edge_type, workspace.edges, authored)
    if canonical is None:
        raise CairnError(f"No edge '{key}' in the current map. `cairn status` lists edge keys.")
    carried = _drop_variants(ws_root, authored, set(variants) - {canonical})
    source = parse_edge_key(canonical)[0]
    current = load_authored(ws_root).get(source, Authored())
    reviews = {**current.edge_reviews}
    whys = {**current.edge_whys}
    if carried.edge_whys and canonical not in whys:
        whys[canonical] = next(iter(carried.edge_whys.values()))  # keep the old explanation
    if review is not None:
        reviews[canonical] = review
    if why:
        whys[canonical] = why
    update = {"edge_reviews": reviews, "edge_whys": whys}
    return save_authored(ws_root, source, current.model_copy(update=update))


def _key_variants(key: str, edge_type: EdgeType) -> tuple[str, ...]:
    source, target, _ = parse_edge_key(key)
    flipped = f"{target}->{source}:{edge_type.value}"
    return (key, flipped) if edge_type in SYMMETRIC_TYPES else (key,)


def _canonical_key(
    variants: tuple[str, ...],
    edge_type: EdgeType,
    edges: Iterable[Edge],
    authored: Mapping[str, Authored],
) -> str | None:
    live = next((e.key for e in edges if e.type is edge_type and e.key in variants), None)
    if live is not None:
        return live
    decided = [k for a in authored.values() for k in (*a.edge_reviews, *a.edge_whys)]
    return next((k for k in decided if k in variants), None)


def _drop_variants(ws_root: Path, authored: Mapping[str, Authored], stale: set[str]) -> Authored:
    """Remove stale keys from every authored file; return their whys so they can be carried over."""
    carried: dict[str, str] = {}
    for repo_id, entry in authored.items():
        if not stale & {*entry.edge_reviews, *entry.edge_whys}:
            continue
        carried.update({k: v for k, v in entry.edge_whys.items() if k in stale})
        cleaned = entry.model_copy(
            update={
                "edge_reviews": {k: v for k, v in entry.edge_reviews.items() if k not in stale},
                "edge_whys": {k: v for k, v in entry.edge_whys.items() if k not in stale},
            }
        )
        save_authored(ws_root, repo_id, cleaned)
    return Authored(edge_whys=carried)


SUMMARY_LIMIT = 500


def set_summary(ws_root: Path, repo_id: str, summary: str, *, aliases: Iterable[str] = ()) -> Path:
    """Store a harness/human-written summary (spec §9.2), stamped with the repo's current HEAD."""
    text = " ".join(summary.split())
    if not text:
        raise CairnInputError("summary", "must not be empty")
    if len(text) > SUMMARY_LIMIT:
        raise CairnInputError(
            "summary", f"is {len(text)} characters; keep it under {SUMMARY_LIMIT}"
        )
    workspace = load_workspace(ws_root)
    if workspace is None:
        raise CairnError("No map found. Run `cairn scan` first.")
    repo = workspace.repo(repo_id)
    if repo is None:
        matches = resolve_repo(workspace, load_authored(ws_root), repo_id, limit=3)
        hint = ", ".join(m.repo_id for m in matches) or "none"
        raise CairnError(f"No repo '{repo_id}'. Did you mean: {hint}?")
    current = load_authored(ws_root).get(repo_id, Authored())
    extra = (a.strip().lower() for a in aliases if a.strip())
    update = {
        "summary": text,
        "summary_sha": repo.head_sha,
        "aliases": tuple(dict.fromkeys((*current.aliases, *extra))),
    }
    return save_authored(ws_root, repo_id, current.model_copy(update=update))
