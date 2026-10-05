"""Where deep indexes live and what each build recorded (spec §23)."""

import json
from pathlib import Path

from pydantic import ConfigDict, ValidationError

from cairn.model.graph import Frozen
from cairn.paths import cairn_dir

META_FILE = "cairn-deep.json"


class DeepMeta(Frozen):
    """Read by cards, status and MCP without loading the graph."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    provider: str
    version: str | None = None
    head_sha: str | None = None
    fingerprint: str | None = None
    built_at: str | None = None
    nodes: int = 0
    hubs: tuple[str, ...] = ()


def deep_root(ws_root: Path) -> Path:
    return cairn_dir(ws_root) / "deep"


def deep_dir(ws_root: Path, repo_id: str) -> Path:
    return deep_root(ws_root) / repo_id


def read_deep_meta(ws_root: Path, repo_id: str) -> DeepMeta | None:
    path = deep_dir(ws_root, repo_id) / META_FILE
    try:
        return DeepMeta.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError):
        return None


def indexed_repos(ws_root: Path) -> list[str]:
    root = deep_root(ws_root)
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / META_FILE).is_file())
