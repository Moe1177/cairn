import json
from pathlib import Path

from cairn.bench.runner import ClaudeRunner, FakeRunner, parse_result

SAMPLE = {
    "type": "result",
    "is_error": False,
    "result": "storefront/lib/cart.ts",
    "num_turns": 3,
    "total_cost_usd": 0.0123,
    "duration_ms": 4567,
    "usage": {
        "input_tokens": 10,
        "cache_creation_input_tokens": 2000,
        "cache_read_input_tokens": 30000,
        "output_tokens": 50,
    },
}


def test_parse_result_reads_usage() -> None:
    r = parse_result(json.dumps(SAMPLE))
    assert (r.num_turns, r.cost_usd, r.fresh_tokens, r.cache_read_tokens) == (
        3,
        0.0123,
        2060,
        30000,
    )
    bad = parse_result("not json")
    assert bad.is_error and "not json" in bad.result_text


def test_command_is_isolated_and_read_only(tmp_path: Path) -> None:
    cmd = ClaudeRunner(model="haiku").command("q?", tmp_path / "ws", None)
    joined = " ".join(cmd)
    assert cmd[:3] == ["claude", "-p", "q?"]
    for flag in (
        "--output-format json",
        "--setting-sources project,local",
        "--no-session-persistence",
        "--permission-mode dontAsk",
        "--strict-mcp-config",
        "--add-dir",
    ):
        assert flag in joined
    assert "--mcp-config" not in cmd
    with_mcp = ClaudeRunner().command("q?", tmp_path, tmp_path / "mcp.json")
    assert with_mcp[with_mcp.index("--mcp-config") + 1] == str(tmp_path / "mcp.json")
    assert "Edit" not in joined and "Write" not in joined


def test_fake_runner(tmp_path: Path) -> None:
    fake = FakeRunner(lambda prompt, cwd: json.dumps({**SAMPLE, "result": f"echo {prompt}"}))
    assert fake.run("hi", tmp_path, tmp_path, None).result_text == "echo hi"
