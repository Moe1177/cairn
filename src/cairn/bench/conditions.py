"""Set up one isolated workspace copy per benchmark condition (spec §11 E2).

A: cold (no map, no CLAUDE.md)      B: hand-written RELATED_REPOS-style doc as CLAUDE.md
C: cairn INDEX only (cards removed)  D: INDEX + cards          E: D + the cairn MCP server
"""

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from cairn.bench.suite import Suite
from cairn.bench.workspace import materialize
from cairn.emit import write_outputs
from cairn.integrations.claude import install_claude
from cairn.integrations.server_command import server_command
from cairn.paths import cairn_dir, cards_dir
from cairn.scan import scan_workspace
from cairn.store.atomic import atomic_write_text

CONDITIONS = ("A", "B", "C", "D", "E")


@dataclass(frozen=True)
class Prepared:
    ws: Path
    mcp_config: Path | None


def prepare(condition: str, suite: Suite, suite_dir: Path, run_dir: Path) -> Prepared:
    ws = materialize(suite_dir / suite.workspace, run_dir / "ws")
    if condition in ("A", "B"):
        shutil.rmtree(cairn_dir(ws), ignore_errors=True)  # no authored summaries either
        if condition == "B":
            doc = (suite_dir / suite.related_repos_doc).read_text(encoding="utf-8")
            atomic_write_text(ws / "CLAUDE.md", doc)
        return Prepared(ws, None)
    write_outputs(ws, scan_workspace(ws))
    install_claude(ws)
    if condition == "C":
        shutil.rmtree(cards_dir(ws))
    if condition != "E":
        return Prepared(ws, None)
    config = run_dir / "mcp.json"
    command = [*server_command(), "--workspace", ws.as_posix()]
    entry = {"command": command[0], "args": command[1:]}
    atomic_write_text(config, json.dumps({"mcpServers": {"cairn": entry}}, indent=2))
    return Prepared(ws, config)
