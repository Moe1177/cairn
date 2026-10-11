"""Codex as a benchmark harness: `codex exec --json`, isolated from the user's Codex setup."""

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cairn.bench.codex_runner import CodexRunner, carried_settings, parse_codex_result
from cairn.bench.run import usage_limit
from cairn.cli import app
from cairn.errors import CairnError


def _events(*events: dict) -> str:
    return "\n".join(json.dumps(e) for e in events) + "\n"


SHELL = {"type": "command_execution", "command": "rg -n gateway", "exit_code": 0}
ANSWER = _events(
    {"type": "thread.started", "thread_id": "t"},
    {"type": "turn.started"},
    {"type": "item.completed", "item": {"type": "agent_message", "text": "Looking."}},
    {"type": "item.started", "item": {**SHELL, "status": "in_progress"}},
    {"type": "item.completed", "item": SHELL},
    {
        "type": "item.completed",
        "item": {"type": "mcp_tool_call", "server": "cairn", "tool": "links"},
    },
    {"type": "item.completed", "item": {"type": "reasoning", "text": "hm"}},
    {"type": "item.completed", "item": {"type": "agent_message", "text": "faas/gateway/main.go"}},
    {
        "type": "turn.completed",
        "usage": {"input_tokens": 25803, "cached_input_tokens": 16256, "output_tokens": 114},
    },
)


def test_the_answer_is_the_last_message_and_cached_input_is_not_fresh() -> None:
    result = parse_codex_result(ANSWER, model="gpt-5")
    assert result.result_text == "faas/gateway/main.go" and not result.is_error
    assert (result.input_tokens, result.cache_read_tokens, result.output_tokens) == (
        9547,
        16256,
        114,
    )
    assert result.fresh_tokens == 9547 + 114
    assert result.tools == (("mcp__cairn__links", 1), ("shell", 1)) and result.num_turns == 2
    assert result.models == ("gpt-5",)


@pytest.mark.parametrize(
    "raw",
    [
        _events({"type": "turn.failed", "error": {"message": "You've hit your usage limit."}}),
        _events({"type": "error", "message": "You've hit your usage limit."}),
    ],
)
def test_a_failed_turn_is_an_error_and_a_usage_limit_stops_the_bench(raw: str) -> None:
    result = parse_codex_result(raw)
    assert result.is_error and usage_limit(result)


def test_no_answer_at_all_is_an_error_with_codex_own_words() -> None:
    result = parse_codex_result("not json\n", "Error: not logged in")
    assert result.is_error and "not logged in" in result.result_text


def test_the_command_is_read_only_ephemeral_and_carries_the_mcp_server(tmp_path: Path) -> None:
    config = tmp_path / "mcp.json"
    server = {"command": "uvx", "args": ["cairnmap", "serve", "--workspace", "/ws"]}
    config.write_text(json.dumps({"mcpServers": {"cairn": server}}), encoding="utf-8")
    cmd = CodexRunner(model="gpt-5").command("q?", tmp_path / "repo", config)
    start = cmd.index("exec")
    assert cmd[start : start + 3] == ["exec", "--json", "--ephemeral"] and cmd[-1] == "q?"
    assert cmd[cmd.index("--sandbox") + 1] == "read-only"
    assert 'approval_policy="never"' in cmd and cmd[cmd.index("--model") + 1] == "gpt-5"
    assert cmd[cmd.index("-C") + 1] == str(tmp_path / "repo")
    assert 'mcp_servers.cairn.command="uvx"' in cmd
    assert 'mcp_servers.cairn.args=["cairnmap", "serve", "--workspace", "/ws"]' in cmd
    assert "--model" not in CodexRunner().command("q?", tmp_path, None)
    disabled = {cmd[i + 1] for i, flag in enumerate(cmd) if flag == "--disable"}
    assert {"apps", "plugins", "hooks", "multi_agent", "browser_use"} <= disabled
    assert 'web_search="disabled"' in cmd


def test_a_global_agents_file_stops_the_benchmark(tmp_path: Path) -> None:
    runner = CodexRunner(home=tmp_path)
    runner.check()  # nothing there: fine
    (tmp_path / "AGENTS.md").write_text("## cairn workspace maps", encoding="utf-8")
    with pytest.raises(CairnError, match="condition A wouldn't be cold"):
        runner.check()


def test_the_condition_context_goes_in_as_developer_instructions(tmp_path: Path) -> None:
    context = '# Index\n- a: "x"'
    cmd = CodexRunner().command("q?", tmp_path, None, instructions=context)
    assert "--ignore-user-config" in cmd and "--ignore-rules" in cmd
    assert f"developer_instructions={json.dumps(context)}" in cmd
    bare = CodexRunner().command("q?", tmp_path, None)
    assert not any(c.startswith("developer_instructions") for c in bare)


def test_run_gives_codex_the_context_and_returns_its_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = tmp_path / "ws"
    (ws / "faas").mkdir(parents=True)
    (ws / "CLAUDE.md").write_text("# Workspace repos (cairn)", encoding="utf-8")
    home = tmp_path / "codex-home"
    home.mkdir()
    (home / "config.toml").write_text('[windows]\nsandbox = "elevated"\n', encoding="utf-8")
    seen: dict = {}

    def fake_run(cmd, **kwargs):
        seen.update(cmd=cmd, stdin=kwargs["stdin"], cwd=kwargs["cwd"])
        return subprocess.CompletedProcess(cmd, 0, stdout=ANSWER, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = CodexRunner(home=home).run("q?", ws / "faas", ws, None)
    assert result.result_text == "faas/gateway/main.go" and result.duration_ms >= 0
    assert 'developer_instructions="# Workspace repos (cairn)"' in seen["cmd"]
    assert 'windows.sandbox="elevated"' in seen["cmd"]
    assert seen["stdin"] is subprocess.DEVNULL and seen["cwd"] == ws / "faas"


def test_the_bench_cli_knows_its_harnesses(tmp_path: Path) -> None:
    suite = Path(__file__).resolve().parents[1] / "bench" / "suites" / "shopverse"
    bad = CliRunner().invoke(app, ["bench", str(suite), "--harness", "gemini"])
    assert bad.exit_code == 1 and "unknown harness" in bad.output


def test_only_the_windows_sandbox_mode_is_carried_over(tmp_path: Path) -> None:
    config = '[windows]\nsandbox = "elevated"\n[mcp_servers.cairn]\ncommand = "x"\n'
    (tmp_path / "config.toml").write_text(config, encoding="utf-8")
    assert carried_settings(tmp_path) == ('windows.sandbox="elevated"',)
    cmd = CodexRunner().command("q?", tmp_path, None, carried=carried_settings(tmp_path))
    assert cmd[-3:] == ["-c", 'windows.sandbox="elevated"', "q?"]
    (tmp_path / "config.toml").write_text("not = [toml", encoding="utf-8")
    assert carried_settings(tmp_path) == ()
    assert carried_settings(tmp_path / "missing") == ()


def test_npm_windows_shim_is_bypassed_so_cmd_exe_never_parses_the_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    from cairn.bench.codex_runner import codex_program

    shim = tmp_path / "codex.cmd"
    shim.write_text("@echo off", encoding="utf-8")
    script = tmp_path / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
    script.parent.mkdir(parents=True)
    script.write_text("", encoding="utf-8")
    found = {"codex": str(shim), "node": str(tmp_path / "node.exe")}
    monkeypatch.setattr(shutil, "which", lambda name: found.get(name))
    assert codex_program() == [str(tmp_path / "node.exe"), str(script)]
    found["codex"] = str(tmp_path / "codex.exe")
    assert codex_program() == [str(tmp_path / "codex.exe")]
