"""Path-reference detector: config files that point at sibling repos via ../ paths."""

import re
from pathlib import Path

from cairn.detectors.base import DetectorContext, DetectorResult, merge_facts
from cairn.model.graph import Fact, FactKind

PATH_REF = re.compile(r"(?:\.\.[/\\])+[A-Za-z0-9_.@-]+(?:[/\\][A-Za-z0-9_.@-]+)*")
_CONFIG_NAMES = frozenset(
    {"package.json", "jsconfig.json", "go.work", "makefile", "pnpm-workspace.yaml", "dockerfile"}
)
_CONFIG_SUFFIXES = frozenset({".yml", ".yaml", ".toml", ".sh", ".ps1", ".code-workspace"})


def is_config_file(name: str) -> bool:
    lowered = name.lower()
    return (
        lowered in _CONFIG_NAMES
        or (lowered.startswith("tsconfig") and lowered.endswith(".json"))
        or lowered.startswith("docker-compose")
        or Path(lowered).suffix in _CONFIG_SUFFIXES
    )


class PathRefsDetector:
    id = "pathrefs"

    def run(self, ctx: DetectorContext) -> DetectorResult:
        ws_root = ctx.workspace_root.resolve()
        repo_root = ctx.repo.root.resolve()
        facts: list[Fact] = []
        for path in ctx.files(is_config_file):
            text = ctx.read(path)
            if text is None:
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                for match in PATH_REF.finditer(line):
                    value = _resolve(path, match.group(0), ws_root, repo_root)
                    if value:
                        evidence = (ctx.evidence(path, line_no, line),)
                        facts.append(Fact(kind=FactKind.PATH_REF, value=value, evidence=evidence))
        return DetectorResult(consumes=merge_facts(facts))


def _resolve(path: Path, ref: str, ws_root: Path, repo_root: Path) -> str | None:
    target = (path.parent / ref.replace("\\", "/")).resolve()
    if not target.is_relative_to(ws_root) or target.is_relative_to(repo_root) or not target.exists():
        return None
    return target.relative_to(ws_root).as_posix()
