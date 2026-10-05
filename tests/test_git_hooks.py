import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cairn.bench.workspace import materialize as materialize_tree
from cairn.cli import app
from cairn.emit import write_outputs
from cairn.integrations.git_hooks import install_hooks, uninstall_hooks
from cairn.scan import scan_workspace


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    for name in ("alpha", "beta"):
        (src / name).mkdir(parents=True)
        (src / name / ".fixture-repo").write_text("", encoding="utf-8")
        (src / name / "README.md").write_text(f"# {name}\n", encoding="utf-8")
    root = materialize_tree(src, tmp_path / "ws").resolve()
    write_outputs(root, scan_workspace(root))
    return root


def _hook(ws: Path, repo: str, name: str = "post-commit") -> Path:
    return ws / repo / ".git" / "hooks" / name


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_hooks_install_and_uninstall(ws: Path) -> None:
    assert install_hooks(ws).changed == ("alpha", "beta")
    hook = _hook(ws, "alpha")
    text = hook.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/sh\n") and "# cairn:start" in text
    assert "refresh" in text and "--quiet" in text
    if os.name != "nt":
        assert os.access(hook, os.X_OK)
    install_hooks(ws)
    assert hook.read_text(encoding="utf-8").count("# cairn:start") == 1
    assert uninstall_hooks(ws).changed == ("alpha", "beta")
    assert not hook.exists()


@pytest.mark.parametrize(
    "original",
    [
        b"#!/bin/sh\ngraphify update --quiet\n",
        b"#!/bin/sh\necho hi",  # no trailing newline
        b"#!/usr/bin/env bash\r\nnpx lint-staged\r\nexit 0\r\n",  # CRLF, ends in exit
        b"#!/bin/sh\n",  # the user's own (empty) hook must survive uninstall
    ],
)
def test_existing_hook_runs_cairn_first_and_is_restored_exactly(ws: Path, original: bytes) -> None:
    # Review Focus 3 + final review I2(b), M1
    hook = _hook(ws, "beta", "post-merge")
    _write(hook, original)
    install_hooks(ws)
    text = hook.read_bytes()
    assert text.index(b"# cairn:start") < len(original.split(b"\n", 1)[0]) + 2
    if b"exit 0" in original:
        assert text.index(b"# cairn:end") < text.index(b"exit 0")
    uninstall_hooks(ws)
    assert hook.read_bytes() == original


def test_non_shell_hook_is_left_alone(ws: Path) -> None:
    # Final review I2(a)
    hook = _hook(ws, "alpha")
    original = b"#!/usr/bin/env python3\nprint('hi')\n"
    _write(hook, original)
    report = install_hooks(ws)
    assert hook.read_bytes() == original
    assert "alpha" not in report.changed
    assert any(repo == "alpha" and "post-commit" in why for repo, why in report.skipped)


def test_core_hooks_path_is_reported_not_silently_ignored(ws: Path) -> None:
    # Final review I2(c)
    subprocess.run(
        ["git", "-C", str(ws / "alpha"), "config", "core.hooksPath", ".husky"], check=True
    )
    report = install_hooks(ws)
    assert report.changed == ("beta",)
    assert not _hook(ws, "alpha").exists()
    assert any(repo == "alpha" and "core.hooksPath" in why for repo, why in report.skipped)


def test_symlinked_hook_is_not_followed(ws: Path, tmp_path: Path) -> None:
    # Final review M2: the link target is usually a tracked file in the repo.
    tracked = ws / "alpha" / "scripts" / "post-commit"
    _write(tracked, b"#!/bin/sh\necho tracked\n")
    hook = _hook(ws, "alpha")
    hook.parent.mkdir(parents=True, exist_ok=True)
    try:
        hook.symlink_to(tracked)
    except OSError:
        pytest.skip("symlinks need extra privileges on this Windows machine")
    report = install_hooks(ws)
    assert tracked.read_bytes() == b"#!/bin/sh\necho tracked\n"
    assert any(repo == "alpha" and "symlink" in why for repo, why in report.skipped)


def test_hooks_cli(ws: Path) -> None:
    runner = CliRunner()
    _write(_hook(ws, "alpha"), b"#!/usr/bin/env node\n")
    result = runner.invoke(app, ["hooks", "install", str(ws)])
    assert result.exit_code == 0
    assert "git hooks installed in 1 repo" in result.output
    assert "skipped alpha" in result.output
    bad = runner.invoke(app, ["hooks", "maybe", str(ws)])
    assert bad.exit_code == 1 and "cairn hooks install" in bad.output
