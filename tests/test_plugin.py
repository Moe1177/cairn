"""Spec §27: the Claude Code plugin, and the cairn commands it runs."""

import json
import os
import re
from pathlib import Path

import pytest
from mcp import Client
from typer.testing import CliRunner

import cairn
from cairn.cli import app
from cairn.integrations.claude import install_claude
from cairn.integrations.content import skill_markdown
from cairn.integrations.homes import claude_home
from cairn.integrations.plugin import (
    CONTEXT_MAX,
    PLUGIN_ENV,
    plugin_enabled,
    session_context,
    unmapped_folder,
)
from cairn.mcp_server import tools
from cairn.mcp_server.server import build_server
from cairn.paths import index_file
from tests.helpers import make_repo

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "cairn"
PIN = f"cairnmap=={cairn.__version__}"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _folder_of_repos(root: Path, names: tuple[str, ...] = ("api", "web", "worker")) -> Path:
    for name in names:
        make_repo(root, name, {"README.md": f"# {name}\n"})
    return root


# --- what the session-start hook says -------------------------------------------------------


def test_inside_a_mapped_workspace_the_hook_prints_the_index(tmp_path: Path) -> None:
    ws = _folder_of_repos(tmp_path / "ws")
    tools.rescan(ws)
    text = session_context(ws / "api")
    assert text.startswith("# Workspace repos (cairn)")
    assert "- api" in text and "- worker" in text
    assert "MCP tools" in text and len(text) <= CONTEXT_MAX


def test_a_claude_md_that_already_loads_the_index_means_the_hook_says_nothing(
    tmp_path: Path,
) -> None:
    ws = _folder_of_repos(tmp_path / "ws")
    tools.rescan(ws)
    install_claude(ws)
    assert session_context(ws / "api") == ""


def test_one_repo_of_an_unmapped_folder_gets_an_offer_to_build_a_map(tmp_path: Path) -> None:
    folder = _folder_of_repos(tmp_path / "code")
    text = session_context(folder / "web")
    assert "holds 3 git repos and has no cairn map yet" in text
    assert "/cairn skill" in text and "without asking" in text
    assert unmapped_folder(folder) == (folder.resolve(), 3)  # opened at the folder itself


def test_a_lone_repo_or_a_plain_folder_gets_nothing(tmp_path: Path) -> None:
    solo = make_repo(tmp_path / "alone", "solo")
    assert session_context(solo) == ""
    assert session_context(tmp_path / "alone") == ""


def test_a_huge_index_is_cut_at_a_line_and_says_how_much_is_left(tmp_path: Path) -> None:
    ws = _folder_of_repos(tmp_path / "ws")
    tools.rescan(ws)
    lines = "\n".join(f"- repo-{i:04}: no summary yet · python" for i in range(2000))
    index_file(ws).write_text(f"# Workspace repos (cairn)\n\n{lines}\n", encoding="utf-8")
    text = session_context(ws / "api")
    assert len(text) <= CONTEXT_MAX
    match = re.search(r"…and (\d+) more repos: read .*INDEX\.md", text)
    assert match is not None
    shown = sum(1 for line in text.splitlines() if line.startswith("- repo-"))
    assert shown + int(match.group(1)) == 2000


def test_the_context_command_prints_the_text_and_never_fails(tmp_path: Path) -> None:
    folder = _folder_of_repos(tmp_path / "code")
    result = CliRunner().invoke(app, ["context", "--from", str(folder / "api")])
    assert result.exit_code == 0 and "has no cairn map yet" in result.output
    ws = _folder_of_repos(tmp_path / "broken")
    (ws / ".cairn").mkdir()
    (ws / ".cairn" / "workspace.json").write_text("{not json", encoding="utf-8")
    result = CliRunner().invoke(app, ["context", "--from", str(ws / "api")])
    assert result.exit_code == 0


def test_the_session_folder_comes_from_claude_code(tmp_path: Path, monkeypatch) -> None:
    folder = _folder_of_repos(tmp_path / "code")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(folder / "worker"))
    result = CliRunner().invoke(app, ["context"])
    assert "holds 3 git repos" in result.output


# --- the plugin being on ---------------------------------------------------------------------


def test_plugin_enabled_from_its_launchers_or_the_users_settings(monkeypatch) -> None:
    settings = claude_home() / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    assert not plugin_enabled()
    settings.write_text(json.dumps({"enabledPlugins": {"cairn@cairn": False}}), encoding="utf-8")
    assert not plugin_enabled()
    settings.write_text(json.dumps({"enabledPlugins": {"cairn@cairn": True}}), encoding="utf-8")
    assert plugin_enabled()
    settings.write_text("{broken", encoding="utf-8")
    assert not plugin_enabled()
    monkeypatch.setenv(PLUGIN_ENV, "1")
    assert plugin_enabled()


def test_init_never_prompts_without_a_terminal(tmp_path: Path) -> None:
    folder = _folder_of_repos(tmp_path / "code")
    result = CliRunner().invoke(app, ["init", str(folder)])  # CliRunner's stdin is no TTY
    assert result.exit_code == 0
    assert "Run `cairn install claude`" in result.output
    assert not (folder / "CLAUDE.md").exists()


def test_init_and_install_leave_claude_code_to_the_plugin(tmp_path: Path, monkeypatch) -> None:
    folder = _folder_of_repos(tmp_path / "code")
    monkeypatch.setenv(PLUGIN_ENV, "1")
    result = CliRunner().invoke(app, ["init", str(folder), "--yes"])
    assert "plugin loads this map into each session" in result.output
    result = CliRunner().invoke(app, ["install", "claude", str(folder)])
    assert "cairn plugin is enabled" in result.output
    assert not (folder / "CLAUDE.md").exists()
    assert not (claude_home() / "skills" / "cairn" / "SKILL.md").exists()


def test_status_names_the_plugin_as_the_claude_code_integration(
    tmp_path: Path, monkeypatch
) -> None:
    ws = _folder_of_repos(tmp_path / "ws")
    tools.rescan(ws)
    monkeypatch.setenv(PLUGIN_ENV, "1")
    result = CliRunner().invoke(app, ["status", str(ws)])
    assert "Claude Code integration: the cairn plugin" in result.output


def test_the_hook_says_once_per_session_when_cairn_is_installed_twice(tmp_path: Path) -> None:
    skill = claude_home() / "skills" / "cairn" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(skill_markdown(), encoding="utf-8")
    solo = make_repo(tmp_path / "alone", "solo")
    text = session_context(solo)
    assert text.count("cairn uninstall claude") == 1
    folder = _folder_of_repos(tmp_path / "code")
    both = session_context(folder / "api")
    assert "has no cairn map yet" in both and "cairn uninstall claude" in both


@pytest.mark.anyio
async def test_the_mcp_server_picks_up_a_map_built_after_it_started(tmp_path: Path) -> None:
    folder = _folder_of_repos(tmp_path / "code")
    server = build_server(None, start=folder / "api")
    async with Client(server) as client:
        before = await client.call_tool("resolve_repo", {"name_or_alias": "web"})
        assert "No cairn workspace found" in before.content[0].text
        tools.rescan(folder)
        after = await client.call_tool("resolve_repo", {"name_or_alias": "web"})
        assert after.content[0].text.startswith("- web")


# --- the plugin's files ------------------------------------------------------------------------


def _json(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def test_the_marketplace_lists_the_plugin_folder() -> None:
    market = _json(".claude-plugin/marketplace.json")
    (entry,) = market["plugins"]
    assert entry["name"] == "cairn" and market["owner"]["name"]
    assert (ROOT / entry["source"] / ".claude-plugin" / "plugin.json").is_file()


def test_every_launcher_runs_the_release_this_plugin_ships_with() -> None:
    manifest = _json("plugins/cairn/.claude-plugin/plugin.json")
    assert manifest["name"] == "cairn" and manifest["version"] == cairn.__version__
    server = _json("plugins/cairn/.mcp.json")["mcpServers"]["cairn"]
    assert server["command"] == "uvx" and server["args"][:2] == ["--from", PIN]
    assert server["env"][PLUGIN_ENV] == "1"
    (hook,) = _json("plugins/cairn/hooks/hooks.json")["hooks"]["SessionStart"][0]["hooks"]
    assert hook["command"] == f"uvx --from {PIN} cairn context"
    wrapper = (PLUGIN / "bin" / "cairn").read_text(encoding="utf-8")
    assert f'exec uvx --from "{PIN}" cairn "$@"' in wrapper
    assert f"export {PLUGIN_ENV}=1" in wrapper


def test_the_plugin_skill_is_the_skill_cairn_installs() -> None:
    shipped = (PLUGIN / "skills" / "cairn" / "SKILL.md").read_text(encoding="utf-8")
    assert shipped == skill_markdown(), "regenerate plugins/cairn/skills/cairn/SKILL.md"
    assert "no map yet" in shipped and "cairn init <folder>" in shipped


def test_the_plugin_readme_passes_the_directory_minimum() -> None:
    words = (PLUGIN / "README.md").read_text(encoding="utf-8").split()
    assert len(words) >= 40


@pytest.mark.skipif(os.name == "nt", reason="the executable bit is a POSIX notion")
def test_the_wrapper_is_executable() -> None:
    assert os.access(PLUGIN / "bin" / "cairn", os.X_OK)
