"""Deep-index providers (spec §6, §23): per-repo code graphs answering "where is X?"."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from cairn.model.graph import Frozen


class DeepStatus(Frozen):
    provider: str
    present: bool = False
    stale: bool = False
    built_sha: str | None = None
    built_at: str | None = None
    version: str | None = None
    nodes: int = 0


@dataclass(frozen=True)
class BuildResult:
    ok: bool
    message: str


class Provider(Protocol):
    id: str

    def available(self) -> bool: ...

    def status(self, ws_root: Path, repo_id: str, repo_root: Path) -> DeepStatus: ...

    def build(
        self, ws_root: Path, repo_id: str, repo_root: Path, *, timeout: float
    ) -> BuildResult: ...

    def graph_path(self, ws_root: Path, repo_id: str) -> Path: ...
