from pathlib import Path

import pytest

from cairn.errors import CairnError, CairnInputError
from cairn.integrations.claude import (
    claude_md,
    install_claude,
    is_installed,
    sync_claude,
    uninstall_claude,
)
from cairn.integrations.registry import list_workspaces, registry_file
from cairn.paths import backups_dir, index_file
from cairn.render.markers import START
from tests.helpers import write


@pytest.fixture(autouse=True)
def _cairn_home(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CAIRN_HOME", str(tmp_path / "home"))


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    write(ws, ".cairn/INDEX.md", "# Workspace repos (cairn)\n- a: thing\n")
    return ws


def test_install_creates_block_and_registers(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    target = install_claude(ws)
    assert target == claude_md(ws)
    assert START in target.read_text(encoding="utf-8")
    assert is_installed(ws)
    assert list_workspaces() == (ws.resolve().as_posix(),)


def test_existing_content_survives_reinstall_and_uninstall(tmp_path: Path) -> None:
    # Review Focus 4
    ws = _ws(tmp_path)
    original = b"# House rules\r\n\r\nUse pnpm.\r\n"
    claude_md(ws).write_bytes(original)
    install_claude(ws)
    write(ws, ".cairn/INDEX.md", "# Workspace repos (cairn)\n- a: changed\n")
    install_claude(ws)
    content = claude_md(ws).read_bytes()
    assert (
        content.startswith(original)
        and content.count(START.encode()) == 1
        and b"changed" in content
    )
    assert (backups_dir(ws) / "CLAUDE.md.orig").read_bytes() == original
    assert uninstall_claude(ws) is True
    assert claude_md(ws).read_bytes() == original
    assert list_workspaces() == ()


def test_uninstall_deletes_file_cairn_created(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    install_claude(ws)
    assert uninstall_claude(ws) is True
    assert not claude_md(ws).exists()
    assert uninstall_claude(ws) is False


def test_install_requires_index(tmp_path: Path) -> None:
    with pytest.raises(CairnError) as info:
        install_claude(tmp_path / "empty")
    assert "cairn scan" in str(info.value)


def test_sync_only_when_installed(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    assert sync_claude(ws) is False and not claude_md(ws).exists()
    install_claude(ws)
    index_file(ws).write_text("# Workspace repos (cairn)\n- a: v2\n", encoding="utf-8")
    assert sync_claude(ws) is True
    assert "v2" in claude_md(ws).read_text(encoding="utf-8")


def test_corrupt_registry_is_reported(tmp_path: Path) -> None:
    path = registry_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{oops", encoding="utf-8")
    with pytest.raises(CairnInputError):
        list_workspaces()


def test_install_leaves_file_untouched_when_block_is_broken(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    original = f"{START}\nold\nIMPORTANT USER NOTES\n"
    claude_md(ws).write_text(original, encoding="utf-8", newline="")
    with pytest.raises(CairnError):
        install_claude(ws)
    with pytest.raises(CairnError):
        uninstall_claude(ws)
    assert claude_md(ws).read_text(encoding="utf-8") == original
