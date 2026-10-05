"""Phase 3 Task 2: the graphify provider (spec §23). A fake graphify records what it was given."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from cairn.bench.workspace import materialize
from cairn.providers.graphify import GraphifyProvider

FAKE = r"""
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
if args[:1] == ["--version"]:
    print("graphify 0.9.77"); raise SystemExit(0)
if os.environ.get("FAKE_SLEEP"):
    import time; time.sleep(float(os.environ["FAKE_SLEEP"]))
out = Path(args[args.index("--out") + 1]) / "graphify-out"
out.mkdir(parents=True, exist_ok=True)
(out / "record.json").write_text(json.dumps({"argv": args, "env": sorted(os.environ)}))
nodes = [{"id": "a", "label": "login()", "source_file": "auth.py", "source_location": "L1"}]
(out / "graph.json").write_text(json.dumps({"nodes": nodes, "links": []}))
"""


def _fake_graphify(tmp_path: Path) -> str:
    script = tmp_path / "fake_graphify.py"
    script.write_text(FAKE, encoding="utf-8")
    if os.name == "nt":
        shim = tmp_path / "graphify.cmd"
        shim.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        shim = tmp_path / "graphify"
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        shim.chmod(0o755)
    return str(shim)


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    src = tmp_path / "src" / "app"
    src.mkdir(parents=True)
    (src / ".fixture-repo").write_text("", encoding="utf-8")
    (src / "auth.py").write_text("def login():\n    return True\n", encoding="utf-8")
    ws = materialize(tmp_path / "src", tmp_path / "ws").resolve()
    return ws, ws / "app"


def _tree(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".git" not in p.relative_to(root).parts
    }


def test_build_is_code_only_out_of_tree_and_scrubbed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws, repo = _workspace(tmp_path)
    before = _tree(repo)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-never-leak")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://evil.example")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
    provider = GraphifyProvider(executable=_fake_graphify(tmp_path))
    result = provider.build(ws, "app", repo, timeout=60)
    assert result.ok, result.message
    out = ws / ".cairn" / "deep" / "app" / "graphify-out"
    record = json.loads((out / "record.json").read_text(encoding="utf-8"))
    argv = record["argv"]
    assert argv[0] == "extract" and "--code-only" in argv
    assert (
        Path(argv[argv.index("--out") + 1]).resolve() == (ws / ".cairn" / "deep" / "app").resolve()
    )
    assert Path(argv[1]).resolve() == repo.resolve()
    leaked = [k for k in record["env"] if k.endswith(("_API_KEY", "_TOKEN", "_BASE_URL"))]
    assert leaked == []
    assert "GRAPHIFY_QUERY_LOG_DISABLE" in record["env"]
    assert _tree(repo) == before  # the repo itself is untouched


def test_status_tracks_staleness(tmp_path: Path) -> None:
    ws, repo = _workspace(tmp_path)
    provider = GraphifyProvider(executable=_fake_graphify(tmp_path))
    assert not provider.status(ws, "app", repo).present
    provider.build(ws, "app", repo, timeout=60)
    status = provider.status(ws, "app", repo)
    assert status.present and not status.stale and status.nodes == 1
    assert status.version == "0.9.77" and status.built_sha
    time.sleep(1.1)
    (repo / "auth.py").write_text("def login():\n    return False\n", encoding="utf-8")
    assert provider.status(ws, "app", repo).stale


def test_missing_executable_and_timeouts_fail_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws, repo = _workspace(tmp_path)
    missing = GraphifyProvider(executable=str(tmp_path / "nope" / "graphify"))
    assert not missing.available()
    result = missing.build(ws, "app", repo, timeout=60)
    assert not result.ok and "graphify" in result.message and "pip install" in result.message
    monkeypatch.setenv("FAKE_SLEEP", "5")
    slow = GraphifyProvider(executable=_fake_graphify(tmp_path), extra_env={"FAKE_SLEEP": "5"})
    timed_out = slow.build(ws, "app", repo, timeout=1)
    assert not timed_out.ok and "time" in timed_out.message.lower()


def test_executable_discovery_prefers_the_running_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cairn.providers import graphify as module

    bin_dir = tmp_path / ("Scripts" if os.name == "nt" else "bin")
    bin_dir.mkdir()
    beside = bin_dir / ("graphify.exe" if os.name == "nt" else "graphify")
    beside.write_text("", encoding="utf-8")
    monkeypatch.setattr(module.sys, "executable", str(bin_dir / "python"))
    monkeypatch.setattr(module.shutil, "which", lambda name: "/elsewhere/graphify")
    assert GraphifyProvider().executable == str(beside)
    beside.unlink()
    assert GraphifyProvider().executable == "/elsewhere/graphify"


@pytest.mark.skipif(shutil.which("graphify") is None, reason="graphify not installed")
def test_real_graphify_builds_without_touching_the_repo(tmp_path: Path) -> None:
    ws, repo = _workspace(tmp_path)
    before = _tree(repo)
    provider = GraphifyProvider()
    result = provider.build(ws, "app", repo, timeout=300)
    assert result.ok, result.message
    assert provider.status(ws, "app", repo).nodes >= 1
    assert _tree(repo) == before
    assert (
        subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True
        ).stdout
        == ""
    )
