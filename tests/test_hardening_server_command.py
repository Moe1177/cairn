"""Phase 2e Task 7 (audit L4; cross-OS 1, 4, 5, 6): a server command that works everywhere."""

import json
import os
from pathlib import Path

import pytest

import cairn
from cairn.cli import app, serve_start
from cairn.emit import write_outputs
from cairn.integrations import server_command as sc
from cairn.integrations.harnesses import install_harness
from cairn.scan import scan_workspace
from tests.helpers import make_repo

EXE = ".exe" if os.name == "nt" else ""


@pytest.mark.parametrize(
    "path",
    [
        "/home/me/.cache/uv/archive-v0/abc/bin/cairn",
        "C:\\Users\\me\\AppData\\Local\\uv\\cache\\archive-v0\\abc\\Scripts\\cairn.exe",
    ],
)
def test_uv_cache_paths_are_ephemeral_in_either_spelling(path: str) -> None:
    # cross-OS 1: Windows-style paths used to slip through on POSIX.
    assert sc.is_ephemeral(Path(path))


def test_running_install_is_preferred(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # pipx/venv: the `cairn` script next to the interpreter running cairn now.
    bin_dir = tmp_path / "venv" / ("Scripts" if os.name == "nt" else "bin")
    bin_dir.mkdir(parents=True)
    script = bin_dir / f"cairn{EXE}"
    script.write_text("", encoding="utf-8")
    monkeypatch.setattr(sc.sys, "executable", str(bin_dir / f"python{EXE}"))
    monkeypatch.setattr(sc.shutil, "which", lambda name: "/elsewhere/cairn")
    assert sc.server_command() == [str(script), "serve"]


def test_version_manager_shims_are_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # cross-OS 4: a pyenv/asdf shim picks the Python by cwd, so it breaks in other projects.
    python = tmp_path / "py" / f"python{EXE}"
    monkeypatch.setattr(sc.sys, "executable", str(python))
    monkeypatch.setattr(sc.shutil, "which", lambda name: "/home/me/.pyenv/shims/cairn")
    assert sc.server_command() == [str(python), "-m", "cairn", "serve"]


def test_uvx_fallback_is_pinned_and_absolute(monkeypatch: pytest.MonkeyPatch) -> None:
    # audit L4 (pin) and cross-OS 5 (GUI apps on macOS don't have ~/.local/bin on PATH).
    cache_python = "/home/me/.cache/uv/archive-v0/abc/bin/python"
    monkeypatch.setattr(sc.sys, "executable", cache_python)
    found = {"uvx": "/home/me/.local/bin/uvx"}
    monkeypatch.setattr(sc.shutil, "which", lambda name: found.get(name))
    assert sc.server_command() == [
        "/home/me/.local/bin/uvx",
        "--from",
        f"cairnmap=={cairn.__version__}",
        "cairn",
        "serve",
    ]


def test_cursor_server_gets_the_open_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # cross-OS 6: Cursor starts stdio servers outside the project; pass the folder explicitly.
    monkeypatch.setenv("CAIRN_HOME", str(tmp_path / "ch"))
    monkeypatch.setenv("CAIRN_USER_HOME", str(tmp_path / "uh"))
    ws = tmp_path / "ws"
    make_repo(ws, "web")
    write_outputs(ws, scan_workspace(ws))
    install_harness("cursor", ws)
    entry = json.loads((tmp_path / "uh" / ".cursor" / "mcp.json").read_text("utf-8"))
    args = entry["mcpServers"]["cairn"]["args"]
    assert args[-3:] == ["serve", "--from", "${workspaceFolder}"]


def test_serve_from_finds_the_workspace_above_a_folder(tmp_path: Path) -> None:
    make_repo(tmp_path, "web")
    write_outputs(tmp_path, scan_workspace(tmp_path))
    nested = tmp_path / "web" / "src"
    nested.mkdir()
    root, start = serve_start(None, nested)
    assert root == tmp_path.resolve() and start == nested
    assert serve_start(None, Path("${workspaceFolder}"))[0] is None  # unexpanded: no workspace
    # Check the registered option, not rendered help: CI forces colour, which splits the text.
    from typer.main import get_command

    serve = get_command(app).commands["serve"]  # type: ignore[attr-defined]
    assert any("--from" in param.opts for param in serve.params)
