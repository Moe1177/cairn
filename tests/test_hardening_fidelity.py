"""Phase 2e Task 8 (cross-OS 3, 7, 8, 9, 10, 11, 14): same files and text on every OS."""

import errno
import os
import stat
import subprocess
import sys
import time
import tomllib
from pathlib import Path

import pytest

from cairn.discover.repos import discover_repos
from cairn.emit import write_outputs
from cairn.integrations import config_files as cf
from cairn.integrations import homes
from cairn.scan import scan_workspace
from cairn.store import lock
from cairn.store.atomic import atomic_write_text
from tests.helpers import make_repo, write
from tests.timing import time_limit


def test_unsupported_locking_warns_and_proceeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # cross-OS 7: NFS without lockd raises ENOLCK; that's not "another cairn process".
    def broken(fd: int) -> None:
        raise OSError(errno.ENOLCK, "No locks available")

    monkeypatch.setattr(lock, "_lock", broken)
    monkeypatch.setattr(lock, "_release", lambda fd: None)
    start = time.monotonic()
    with lock.workspace_lock(tmp_path, timeout=30):
        pass
    assert time.monotonic() - start < time_limit(1)
    assert "locking" in capsys.readouterr().err


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_rewrites_keep_the_files_mode(tmp_path: Path) -> None:
    # cross-OS 8: mkstemp creates 0600, which made shared CLAUDE.md files unreadable.
    shared = tmp_path / "CLAUDE.md"
    shared.write_text("x", encoding="utf-8")
    shared.chmod(0o664)
    atomic_write_text(shared, "y")
    assert stat.S_IMODE(shared.stat().st_mode) == 0o664
    old = os.umask(0o022)
    try:
        atomic_write_text(tmp_path / "new.md", "z")
    finally:
        os.umask(old)
    assert stat.S_IMODE((tmp_path / "new.md").stat().st_mode) == 0o644


def test_codex_toml_keeps_non_ascii_paths(tmp_path: Path) -> None:
    # cross-OS 9: json.dumps' \\ud83d surrogate escapes are invalid TOML.
    config = tmp_path / "config.toml"
    command = ["/home/émile/\U0001f600/cairn", "serve"]
    cf.set_toml_server(config, command, label="codex")
    loaded = tomllib.loads(config.read_text(encoding="utf-8"))
    assert loaded["mcp_servers"]["cairn"]["command"] == command[0]


def test_app_root_order_is_the_same_on_every_os(tmp_path: Path) -> None:
    # cross-OS 10: Windows paths sort case-insensitively, POSIX ones don't.
    for name in ("alpha", "Beta", "Zeta"):
        write(tmp_path, f"mono/{name}/package.json", f'{{"name": "{name.lower()}"}}')
    make_repo(tmp_path, "mono")
    (location,) = discover_repos(tmp_path)
    assert [p.name for p in location.app_roots] == ["Beta", "Zeta", "alpha"]


def test_claude_config_dir_is_honoured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # cross-OS 14: Claude Code reads skills from $CLAUDE_CONFIG_DIR when it's set.
    monkeypatch.delenv("CAIRN_USER_HOME", raising=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-config"))
    assert homes.claude_home() == tmp_path / "claude-config"
    monkeypatch.setenv("CAIRN_USER_HOME", str(tmp_path / "uh"))  # test isolation wins
    assert homes.claude_home() == tmp_path / "uh" / ".claude"


def test_piped_text_is_utf8_both_ways(tmp_path: Path) -> None:
    # cross-OS 3 and 11: piped stdin/stdout used the console code page (cp1252) on Windows.
    ws = tmp_path / "répo ws"
    make_repo(ws, "app")
    write_outputs(ws, scan_workspace(ws))
    env = {**os.environ, "CAIRN_HOME": str(tmp_path / "ch"), "CAIRN_USER_HOME": str(tmp_path)}
    env.pop("PYTHONIOENCODING", None)
    env.pop("PYTHONUTF8", None)
    done = subprocess.run(
        [sys.executable, "-m", "cairn", "set-summary", "app", "-", str(ws)],
        input="Café ordering API → used by web.".encode(),
        capture_output=True,
        env=env,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert "répo ws" in done.stdout.decode("utf-8")
    saved = (ws / ".cairn" / "authored" / "app.yaml").read_text(encoding="utf-8")
    assert "Café ordering API → used by web." in saved


def test_registry_keeps_one_entry_per_folder_whatever_the_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # cross-OS 12: macOS resolve() keeps the typed case, so ~/Work and ~/work were two entries.
    from cairn.integrations.registry import list_workspaces, register_workspace

    monkeypatch.setenv("CAIRN_HOME", str(tmp_path / "ch"))
    ws = tmp_path / "Work"
    ws.mkdir()
    variant = tmp_path / "work"
    if not variant.exists():
        pytest.skip("case-sensitive filesystem: these are different folders")
    register_workspace(ws)
    register_workspace(variant)
    assert len(list_workspaces()) == 1
