"""Phase 2e Task 6 (audit M4, M5): repos can't choose the MCP workspace or inject commands."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from cairn.detectors.profile import ProfileDetector
from cairn.discover.repos import discover_repos
from cairn.emit import write_outputs
from cairn.mcp_server.server import find_workspace
from cairn.model.graph import Repo
from cairn.scan import scan_workspace
from tests.helpers import ctx_for, make_repo, write


def test_a_map_committed_inside_a_repo_is_not_trusted(tmp_path: Path) -> None:
    # audit M4: a repo ships its own .cairn/workspace.json to hijack the server.
    ws = tmp_path / "ws"
    make_repo(ws, "web")
    write_outputs(ws, scan_workspace(ws))
    evil = make_repo(ws, "evil")
    write(evil, ".cairn/workspace.json", json.dumps({"schema_version": 1}))
    (evil / "sub").mkdir()
    assert find_workspace(evil / "sub") == ws.resolve()


@pytest.mark.parametrize(
    ("repo_id", "path"),
    [
        ("../x", "x"),
        ("a/b", "a/b"),
        ("C:\\secret", "x"),
        ("x\ny", "x"),
        ("..", "x"),
        ("x", "/etc"),
        ("x", "../outside"),
        ("x", "C:/Users/me"),
        ("x", "a/../../b"),
    ],
)
def test_repo_ids_and_paths_must_stay_inside(repo_id: str, path: str) -> None:
    # audit M4: ids become card file names; paths are joined to the workspace root.
    with pytest.raises(ValidationError):
        Repo(id=repo_id, path=path)


def test_ordinary_repo_ids_and_paths_are_valid() -> None:
    Repo(id="group--svc", path="group/svc", app_roots=("group/svc/web",))
    Repo(id="shop-admin", path="shop-admin")


def test_unsafe_folder_names_get_no_run_command(tmp_path: Path) -> None:
    # audit M5: a folder named `web;touch PWNED` must not become a shell command.
    scripts = json.dumps({"name": "x", "scripts": {"dev": "vite"}})
    repo = make_repo(
        tmp_path, "mono", {"web;touch PWNED/package.json": scripts, "api/package.json": scripts}
    )
    location = next(loc for loc in discover_repos(tmp_path) if loc.id == "mono")
    ctx = ctx_for(tmp_path, repo, app_roots=list(location.app_roots))
    commands = [c.run for c in ProfileDetector().run(ctx).commands]
    assert commands and all("PWNED" not in run for run in commands)
    assert any(run.startswith("cd api && ") for run in commands)
