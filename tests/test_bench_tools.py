"""0.7.1: benchmark runs record which tools the agent called (B4 couldn't tell whether agents
used cairn's MCP tools at all)."""

import json
from pathlib import Path

from cairn.bench.grading import Grade
from cairn.bench.report import load_records, render_markdown
from cairn.bench.run import RunRecord
from cairn.bench.runner import ClaudeRunner, RunResult, parse_result


def _tool_use(*names: str) -> str:
    content = [
        {"type": "tool_use", "id": f"t{i}", "name": n, "input": {}} for i, n in enumerate(names)
    ]
    return json.dumps({"type": "assistant", "message": {"role": "assistant", "content": content}})


STREAM = "\n".join(
    [
        json.dumps({"type": "system", "subtype": "init", "tools": ["Grep", "Read"]}),
        _tool_use("Grep", "mcp__cairn__query"),
        json.dumps({"type": "user", "message": {"content": [{"type": "tool_result"}]}}),
        _tool_use("Grep"),
        json.dumps(
            {
                "type": "result",
                "result": "answer",
                "num_turns": 3,
                "total_cost_usd": 0.02,
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "modelUsage": {"claude-haiku-4-5": {}},
            }
        ),
    ]
)


def test_a_stream_is_parsed_for_its_result_and_its_tool_calls() -> None:
    result = parse_result(STREAM)
    assert (result.result_text, result.num_turns, result.cost_usd) == ("answer", 3, 0.02)
    assert result.tools == (("Grep", 2), ("mcp__cairn__query", 1))
    assert not result.is_error


def test_a_single_json_result_still_parses() -> None:
    result = parse_result(json.dumps({"result": "x", "num_turns": 1}))
    assert result.result_text == "x" and result.tools == ()


def test_runs_ask_claude_for_a_stream() -> None:
    command = ClaudeRunner(model="haiku").command("q", Path("ws"), None)
    assert command[command.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in command


def _record(condition: str, tools: tuple[tuple[str, int], ...]) -> RunRecord:
    grade = Grade(success=True, recall=1.0, precision=1.0)
    return RunRecord(condition, "t1", 0, grade, RunResult(result_text="a", tools=tools))


def test_logs_with_and_without_tools_load(tmp_path: Path) -> None:
    log = tmp_path / "run.jsonl"
    old = {
        "condition": "A",
        "task_id": "t",
        "run": 0,
        "grade": {"success": True, "recall": 1.0, "precision": 1.0},
        "result": {"result_text": "x"},
    }
    new = {**old, "condition": "E", "result": {"result_text": "x", "tools": [["Grep", 2]]}}
    log.write_text(json.dumps(old) + "\n" + json.dumps(new) + "\n", encoding="utf-8")
    records = load_records(log)
    assert records[0].result.tools == () and records[1].result.tools == (("Grep", 2),)


def test_the_report_says_how_often_cairn_s_tools_were_used() -> None:
    records = [
        _record("D", (("Grep", 4),)),
        _record("E", (("Grep", 2), ("mcp__cairn__query", 1))),
        _record("E", (("Grep", 3),)),
    ]
    text = render_markdown(records)
    assert "## Tools used" in text
    assert "| E | 2 | 1 (50%) | 0.5 |" in text
