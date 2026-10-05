import json
import tomllib
from pathlib import Path

import pytest

import cairn.integrations.harnesses as h
from cairn.emit import write_outputs
from cairn.scan import scan_workspace
from tests.helpers import make_repo


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("CAIRN_USER_HOME", str(home))
    monkeypatch.setenv("CAIRN_HOME", str(home / ".cairn"))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    calls: list[list[str]] = []

    def fake_cli(args: list[str]) -> tuple[int, str]:
        calls.append(args)
        return 0, "Added stdio MCP server cairn"

    monkeypatch.setattr(h, "_claude_cli", fake_cli)
    ws = tmp_path / "ws"
    make_repo(ws, "alpha", {"package.json": '{"name": "alpha"}'})
    write_outputs(ws, scan_workspace(ws))
    return home, ws, calls


def test_codex_install_and_uninstall(env) -> None:
    home, ws, _ = env
    h.install_harness("codex", ws)
    assert ws.resolve().as_posix() in (home / ".codex" / "AGENTS.md").read_text(encoding="utf-8")
    assert (home / ".codex" / "skills" / "cairn" / "SKILL.md").is_file()
    cfg = tomllib.loads((home / ".codex" / "config.toml").read_text(encoding="utf-8"))
    assert cfg["mcp_servers"]["cairn"]["args"][-1] == "serve"
    assert h.installed_harnesses(ws) == ("codex",)
    h.uninstall_harness("codex", ws)
    assert not (home / ".codex" / "AGENTS.md").exists()
    assert not (home / ".codex" / "skills" / "cairn").exists()
    assert h.installed_harnesses(ws) == ()


def test_gemini_and_cursor_keep_existing_settings(env) -> None:
    home, ws, _ = env
    settings = home / ".gemini" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('{"theme": "dark"}', encoding="utf-8")
    h.install_harness("gemini", ws)
    h.install_harness("cursor", ws, per_repo=True)
    assert json.loads(settings.read_text(encoding="utf-8"))["theme"] == "dark"
    assert (home / ".gemini" / "commands" / "cairn.toml").is_file()
    mcp = json.loads((home / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    assert "cairn" in mcp["mcpServers"]
    rule = ws / "alpha" / ".cursor" / "rules" / "cairn.mdc"
    exclude = ws / "alpha" / ".git" / "info" / "exclude"
    assert rule.is_file()
    assert ".cursor/rules/cairn.mdc" in exclude.read_text(encoding="utf-8")
    h.uninstall_harness("cursor", ws)
    assert not rule.exists()
    assert ".cursor/rules/cairn.mdc" not in exclude.read_text(encoding="utf-8")


def test_claude_install_registers_mcp_and_skill(env) -> None:
    home, ws, calls = env
    lines = h.install_harness("claude", ws)
    assert (ws / "CLAUDE.md").is_file()
    assert (home / ".claude" / "skills" / "cairn" / "SKILL.md").is_file()
    assert calls[0][:4] == ["mcp", "add", "--scope", "user"] and calls[0][4] == "cairn"
    assert any("registered" in line for line in lines)
    h.uninstall_harness("claude", ws)
    assert calls[-1] == ["mcp", "remove", "--scope", "user", "cairn"]
    assert not (home / ".claude" / "skills" / "cairn").exists()


def test_claude_without_cli_prints_the_command(env, monkeypatch) -> None:
    _, ws, _ = env
    monkeypatch.setattr(h, "_claude_cli", lambda args: None)
    lines = h.install_harness("claude", ws)
    assert any("claude mcp add --scope user cairn --" in line for line in lines)


def test_pointer_lists_every_registered_workspace(env, tmp_path: Path) -> None:
    home, ws, _ = env
    other = tmp_path / "ws2"
    make_repo(other, "beta")
    write_outputs(other, scan_workspace(other))
    h.install_harness("codex", ws)
    h.install_harness("claude", other)  # registers a second workspace; codex pointer must follow
    text = (home / ".codex" / "AGENTS.md").read_text(encoding="utf-8")
    assert ws.resolve().as_posix() in text and other.resolve().as_posix() in text


def test_manual_command_uses_native_quoting() -> None:
    # Dogfood: POSIX single quotes don't work in Windows cmd.
    cmd = [r"C:\Program Files\cairn\cairn.exe", "serve"]
    assert h._display(cmd, windows=True) == r'"C:\Program Files\cairn\cairn.exe" serve'
    assert h._display(["/usr/bin/cairn", "serve"], windows=False) == "/usr/bin/cairn serve"
