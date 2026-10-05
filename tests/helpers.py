"""Small builders for test workspaces."""

from collections.abc import Mapping, Sequence
from pathlib import Path

from cairn.config import CairnConfig
from cairn.detectors.base import DetectorContext
from cairn.discover.repos import RepoLocation


def write(root: Path, rel: str, text: str = "") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_repo(ws: Path, name: str, files: dict[str, str] | None = None) -> Path:
    root = ws / name
    (root / ".git").mkdir(parents=True)
    for rel, text in (files or {}).items():
        write(root, rel, text)
    return root


def ctx_for(
    ws: Path,
    repo_root: Path,
    *,
    app_roots: Sequence[Path] | None = None,
    alias_table: Mapping[str, str] | None = None,
    config: CairnConfig | None = None,
) -> DetectorContext:
    location = RepoLocation(
        id=repo_root.name,
        root=repo_root.resolve(),
        app_roots=tuple(p.resolve() for p in (app_roots or [repo_root])),
    )
    return DetectorContext(
        workspace_root=ws.resolve(),
        repo=location,
        config=config or CairnConfig(),
        alias_table=dict(alias_table or {}),
    )
