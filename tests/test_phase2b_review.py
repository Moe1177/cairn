"""Regression tests for the Phase 2b final review (fixes to global-config safety and the server)."""

import json
import subprocess
import threading
import tomllib
from pathlib import Path

import pytest
from mcp import Client

import cairn.integrations.harnesses as h
import cairn.integrations.server_command as sc
from cairn.emit import write_outputs
from cairn.errors import CairnInputError
from cairn.integrations import config_files as cf
from cairn.integrations.registry import list_workspaces
from cairn.mcp_server import tools
from cairn.mcp_server.server import build_server
from cairn.scan import scan_workspace
from cairn.store.atomic import atomic_write_text
from tests.helpers import make_repo

CMD = ["C:\\tools\\cairn.exe", "serve"]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("CAIRN_USER_HOME", str(home))
    monkeypatch.setenv("CAIRN_HOME", str(home / ".cairn"))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(h, "_claude_cli", lambda args: (0, "ok"))
    ws = tmp_path / "ws"
    make_repo(ws, "alpha", {"package.json": '{"name": "alpha"}'})
    write_outputs(ws, scan_workspace(ws))
    return home, ws


# I1: never leave Codex with an invalid config.toml
def test_inline_mcp_servers_table_is_refused_not_corrupted(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    original = 'mcp_servers = { foo = { command = "x" } }\n'
    path.write_text(original, encoding="utf-8")
    with pytest.raises(CairnInputError):
        cf.set_toml_server(path, CMD, label="codex")
    assert path.read_text(encoding="utf-8") == original


def test_toml_with_bom_is_edited_and_keeps_its_bom(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_bytes('\ufeffmodel = "o4"\n'.encode())
    cf.set_toml_server(path, CMD, label="codex")
    raw = path.read_bytes().decode("utf-8")
    assert raw.startswith("\ufeff")
    assert tomllib.loads(raw.removeprefix("\ufeff"))["mcp_servers"]["cairn"]["args"] == ["serve"]


# I2: undecodable files are refused cleanly, and install all keeps going
def test_non_utf8_config_is_a_clean_error(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b'{"theme": "caf\xe9"}')
    with pytest.raises(CairnInputError):
        cf.set_json_server(path, CMD, label="gemini")


def test_install_all_survives_non_utf8_and_status_works(env) -> None:
    home, ws = env
    settings = home / ".gemini" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_bytes(b'{"theme": "caf\xe9"}')
    results = {}
    for name in h.HARNESSES:
        try:
            h.install_harness(name, ws)
            results[name] = "ok"
        except CairnInputError:
            results[name] = "refused"
    assert results == {"claude": "ok", "codex": "ok", "gemini": "refused", "cursor": "ok"}
    assert h.installed_harnesses(ws) == ("claude", "codex", "cursor")


def test_json_edits_keep_unicode_and_crlf(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes('{\r\n  "greeting": "café ☕"\r\n}\r\n'.encode())
    cf.set_json_server(path, CMD, label="gemini")
    raw = path.read_bytes().decode("utf-8")
    assert "café ☕" in raw and "\r\n" in raw and "\\u00e9" not in raw


# I3: symlinked config files stay symlinks
def test_atomic_write_follows_symlinks(tmp_path: Path) -> None:
    real = tmp_path / "dotfiles" / "config.toml"
    real.parent.mkdir()
    real.write_text("a = 1\n", encoding="utf-8")
    link = tmp_path / "config.toml"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("this OS refused to create a file symlink")
    atomic_write_text(link, "a = 2\n")
    assert link.is_symlink()
    assert real.read_text(encoding="utf-8") == "a = 2\n"


# I4: claude mcp failures are reported, stale registrations replaced
def test_failed_claude_mcp_add_is_not_reported_as_success(env, monkeypatch) -> None:
    _, ws = env
    monkeypatch.setattr(h, "_claude_cli", lambda args: (1, "error: Invalid configuration file"))
    lines = h.install_harness("claude", ws)
    assert not any("registered" in line for line in lines)
    assert any("failed" in line and "claude mcp add --scope user cairn" in line for line in lines)


def test_existing_claude_registration_is_replaced(env, monkeypatch) -> None:
    _, ws = env
    calls: list[list[str]] = []

    def fake(args: list[str]) -> tuple[int, str]:
        calls.append(args)
        if args[1] == "add" and len([c for c in calls if c[1] == "add"]) == 1:
            return 1, "MCP server cairn already exists in user config"
        return 0, "ok"

    monkeypatch.setattr(h, "_claude_cli", fake)
    lines = h.install_harness("claude", ws)
    assert [c[1] for c in calls] == ["add", "remove", "add"]
    assert any("re-registered" in line for line in lines)


# I5: never register a path inside uv's cache
def test_ephemeral_uvx_environment_registers_uvx_command(monkeypatch) -> None:
    cache_exe = "C:\\Users\\me\\AppData\\Local\\uv\\cache\\archive-v0\\abc\\Scripts\\cairn.exe"
    monkeypatch.setattr(sc.shutil, "which", lambda name: cache_exe)
    assert sc.server_command() == ["uvx", "--from", "cairnmap", "cairn", "serve"]
    assert sc.is_ephemeral(Path(cache_exe))
    assert not sc.is_ephemeral(Path("C:/Users/me/.local/bin/cairn.exe"))


# I6: concurrent rescans and reads don't fail
def test_concurrent_rescans_do_not_fail(materialize) -> None:
    ws = materialize("mini-eats").resolve()
    tools.rescan(ws)
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            for _ in range(5):
                tools.rescan(ws)
                assert tools.card_text(ws, "eats").startswith("# eats")
        except BaseException as exc:  # collect anything, including PermissionError
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


# I7: uninstalling one harness keeps the workspace for the others
def test_uninstalling_claude_keeps_workspace_for_other_harnesses(env) -> None:
    home, ws = env
    for name in ("claude", "codex"):
        h.install_harness(name, ws)
    h.uninstall_harness("claude", ws)
    assert list_workspaces() == (ws.resolve().as_posix(),)
    h.install_harness("gemini", ws)
    assert ws.resolve().as_posix() in (home / ".codex" / "AGENTS.md").read_text(encoding="utf-8")
    for name in ("codex", "gemini"):
        h.uninstall_harness(name, ws)
    assert list_workspaces() == ()


def test_refused_install_does_not_leave_workspace_registered(env) -> None:
    home, ws = env
    cfg = home / ".codex" / "config.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('[mcp_servers.cairn]\ncommand = "mine"\n', encoding="utf-8")
    with pytest.raises(CairnInputError):
        h.install_harness("codex", ws)
    assert list_workspaces() == ()


def test_uninstall_cursor_without_a_map_still_succeeds(env, tmp_path: Path) -> None:
    _, ws = env
    h.install_harness("cursor", ws)
    lines = h.uninstall_harness("cursor", tmp_path / "elsewhere")
    assert any("Cursor: cairn removed" in line for line in lines)


# I8: related/query check staleness too
def test_related_rescans_a_stale_repo(materialize) -> None:
    ws = materialize("mini-eats").resolve()
    tools.rescan(ws)
    assert "references path" in tools.related_text(ws, "eats-admin")
    repo = ws / "eats-admin"
    (repo / "eats-admin" / "tsconfig.json").write_text("{}", encoding="utf-8")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@e.com", "-c", "commit.gpgsign=false"]
    subprocess.run([*git, "commit", "-qam", "drop path"], cwd=repo, check=True, capture_output=True)
    assert "references path" not in tools.related_text(ws, "eats-admin")


# Re-graded: serve outside a workspace answers instead of failing
@pytest.mark.anyio
async def test_server_without_workspace_explains_how_to_start(tmp_path: Path) -> None:
    server = build_server(None, start=tmp_path)
    async with Client(server) as client:
        result = await client.call_tool("resolve_repo", {"name_or_alias": "x"})
        text = result.content[0].text
    assert "No cairn workspace" in text and "cairn init" in text


@pytest.mark.anyio
async def test_unexpected_tool_errors_are_readable(materialize, monkeypatch) -> None:
    ws = materialize("mini-eats").resolve()
    tools.rescan(ws)

    def boom(*args, **kwargs):
        raise PermissionError(13, "Access is denied", "INDEX.md")

    monkeypatch.setattr(tools, "resolve_text", boom)
    async with Client(build_server(ws)) as client:
        result = await client.call_tool("resolve_repo", {"name_or_alias": "x"})
    assert (
        result.content[0].text.startswith("cairn error:")
        and "Access is denied" in result.content[0].text
    )


def test_json_round_trip_still_valid(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    cf.set_json_server(path, CMD, label="cursor")
    assert json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["cairn"]["command"] == CMD[0]
