"""0.7.1: benchmark runs record which tools the agent called (B4 couldn't tell whether agents
used cairn's MCP tools at all)."""

import json
from pathlib import Path

import pytest

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


def test_a_stream_without_a_result_line_is_an_error() -> None:
    """claude can die after its init line: that is not a clean run with an empty answer."""
    init = json.dumps({"type": "system", "subtype": "init", "tools": ["Grep"]})
    for raw in (init, init + "\n" + _tool_use("Grep")):
        result = parse_result(raw)
        assert result.is_error


def test_odd_stream_lines_never_crash_the_run() -> None:
    lines = [
        json.dumps({"type": "assistant", "message": "not a dict"}),
        json.dumps({"type": "assistant", "message": {"content": "text"}}),
        json.dumps({"type": "result", "result": "a", "usage": "oops", "modelUsage": []}),
    ]
    result = parse_result("\n".join(lines))
    assert result.result_text == "a" and result.input_tokens == 0


@pytest.mark.parametrize(
    "text",
    [
        "Claude AI usage limit reached|1760000000",
        "You've hit your session limit · resets 5pm",
        "Rate limit exceeded",
        "Weekly limit reached",
    ],
)
def test_every_limit_wording_is_detected(text: str) -> None:
    from cairn.bench.run import usage_limit

    assert usage_limit(RunResult(result_text=text, is_error=True))


def test_the_combined_report_shows_tools_too() -> None:
    from cairn.bench.report import render_combined

    records = [_record("E", (("mcp__cairn__query", 1),)), _record("E", (("Grep", 1),))]
    text = render_combined({"All suites / haiku": records})
    assert "### Tools used" in text and "| E | 2 | 1 (50%) |" in text


def test_a_no_result_run_keeps_stderr_and_drops_the_stream() -> None:
    """The init event is often several KB: stderr must survive, and the JSON stream (tool
    results quoting the benchmark repo's code) must not be graded or matched as a limit."""
    from cairn.bench.run import usage_limit

    init = json.dumps({"type": "system", "subtype": "init", "tools": ["x" * 3000]})
    tool_output = json.dumps(
        {"type": "user", "message": {"content": "raise RateLimitError('rate limit')"}}
    )
    result = parse_result(init + "\n" + tool_output, "Claude AI usage limit reached|1760000000")
    assert result.is_error and "usage limit reached" in result.result_text
    assert "RateLimitError" not in result.result_text and usage_limit(result)
    quiet = parse_result(init + "\n" + tool_output, "")
    assert quiet.is_error and not usage_limit(quiet)


@pytest.mark.parametrize(
    "text",
    [
        "You've hit your limit · resets 3pm",
        "5-hour limit reached ∙ resets 3am",
        "Request was rate limited",
        "usage limits exceeded",
        'API Error: 429 {"type":"error","error":{"type":"rate_limit_error"}}',
    ],
)
def test_more_limit_wordings_are_detected(text: str) -> None:
    from cairn.bench.run import usage_limit

    assert usage_limit(RunResult(result_text=text, is_error=True))
