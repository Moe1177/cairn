"""Write harness/human-authored content (.cairn/authored/<repo>.yaml) without clobbering it."""

import re
from pathlib import Path
from typing import Literal

import yaml

from cairn.errors import CairnError, CairnInputError
from cairn.load import load_authored
from cairn.model.graph import SYMMETRIC_TYPES, EdgeType
from cairn.model.overrides import Authored
from cairn.paths import authored_dir
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
    """Record a review and/or explanation for an existing edge; other authored fields are kept."""
    source, target, edge_type = parse_edge_key(key)
    workspace = load_workspace(ws_root)
    if workspace is None:
        raise CairnError("No map found. Run `cairn scan` first.")
    pairs = {(source, target)}
    if edge_type in SYMMETRIC_TYPES:
        pairs.add((target, source))
    if not any((e.source, e.target) in pairs and e.type is edge_type for e in workspace.edges):
        raise CairnError(f"No edge '{key}' in the current map. `cairn status` lists edge keys.")
    current = load_authored(ws_root).get(source, Authored())
    update: dict[str, object] = {}
    if review is not None:
        update["edge_reviews"] = {**current.edge_reviews, key: review}
    if why:
        update["edge_whys"] = {**current.edge_whys, key: why}
    return save_authored(ws_root, source, current.model_copy(update=update))
