"""Set up one isolated workspace copy per benchmark condition (spec §11 E2).

A: cold (no map, no CLAUDE.md)      B: hand-written RELATED_REPOS-style doc as CLAUDE.md
C: cairn INDEX only (no cards/graph)  D: INDEX + cards          E: D + the cairn MCP server
"""

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from cairn.bench.sources import fetch_sources, remotes
from cairn.bench.suite import Suite
from cairn.bench.workspace import materialize
from cairn.emit import write_outputs
from cairn.integrations.claude import install_claude
from cairn.integrations.server_command import server_command
from cairn.org.view import org_index_lines
from cairn.paths import cairn_dir, index_file
from cairn.render.index import render_index
from cairn.scan import scan_workspace
from cairn.store.atomic import atomic_write_text

CONDITIONS = ("A", "B", "C", "D", "E")
_PRISTINE = "suite-cairn"  # the suite's own .cairn (authored summaries), kept beside the workspace


@dataclass(frozen=True)
class Prepared:
    ws: Path
    mcp_config: Path | None


def prepare(
    condition: str, suite: Suite, suite_dir: Path, run_dir: Path, source: Path | None = None
) -> Prepared:
    """`source`: the fixture tree (fetched once per benchmark for an OSS suite)."""
    return set_up(
        condition, suite, suite_dir, make_workspace(suite, suite_dir, run_dir, source), run_dir
    )


def make_workspace(
    suite: Suite, suite_dir: Path, run_dir: Path, source: Path | None = None
) -> Path:
    """The suite's repos as git repos under `run_dir`, ready for set_up."""
    tree = source or fetch_sources(suite_dir, suite)
    # A fetched upstream tree keeps its own names: renaming dot-git to .git would let it plant
    # hooks or config that the fixture commit would run.
    return materialize(tree, run_dir / "ws", remotes=remotes(suite), rename_dots=not suite.sources)


def set_up(condition: str, suite: Suite, suite_dir: Path, ws: Path, run_dir: Path) -> Prepared:
    """Make `ws` what `condition` needs, whatever an earlier condition left in it: one workspace
    serves every condition, since copying a large suite into git repos takes many minutes."""
    pristine = run_dir / _PRISTINE
    if not pristine.exists():  # first use: keep what the suite ships in .cairn (authored notes)
        if cairn_dir(ws).is_dir():
            shutil.copytree(cairn_dir(ws), pristine)
        else:
            pristine.mkdir(parents=True)
    shutil.rmtree(cairn_dir(ws), ignore_errors=True)
    (ws / "CLAUDE.md").unlink(missing_ok=True)
    if condition in ("A", "B"):  # no map, and no authored summaries either
        if condition == "B":
            doc = (suite_dir / suite.related_repos_doc).read_text(encoding="utf-8")
            atomic_write_text(ws / "CLAUDE.md", doc)
        return Prepared(ws, None)
    shutil.copytree(pristine, cairn_dir(ws), dirs_exist_ok=True)
    result = scan_workspace(ws)
    write_outputs(ws, result)
    if condition == "C":
        # INDEX only: no card pointer in the text, and no cards or graph JSON to read instead.
        text = render_index(
            result.workspace,
            result.authored,
            threshold=result.config.index_threshold,
            with_cards=False,
            # The org's repos stay in (only an org-configured workspace has any): with no cards
            # to read, they are all C knows of the repos it doesn't have.
            org_lines=org_index_lines(ws, result.workspace, result.config),
        )
        atomic_write_text(index_file(ws), text)
        install_claude(ws)
        shutil.rmtree(cairn_dir(ws))
        return Prepared(ws, None)
    install_claude(ws)
    if condition != "E":
        return Prepared(ws, None)
    config = run_dir / "mcp.json"
    command = [*server_command(), "--workspace", ws.as_posix()]
    entry = {"command": command[0], "args": command[1:]}
    atomic_write_text(config, json.dumps({"mcpServers": {"cairn": entry}}, indent=2))
    return Prepared(ws, config)
