"""Phase 4 Task 6: uncertainty, paired tests and break-even in benchmark reports."""

import json
from dataclasses import asdict
from pathlib import Path

from cairn.bench.grading import Grade
from cairn.bench.report import load_records, render_combined, render_markdown
from cairn.bench.run import RunRecord
from cairn.bench.runner import RunResult


def _records() -> list[RunRecord]:
    """6 tasks x 2 runs: A always fails and costs 0.10; C always passes and costs 0.04."""
    out = []
    for task in range(6):
        for run in range(2):
            out.append(
                RunRecord(
                    "A", f"t{task}", run, Grade(False, 0.0, 0.0), RunResult("a", cost_usd=0.10)
                )
            )
            out.append(
                RunRecord(
                    "C", f"t{task}", run, Grade(True, 1.0, 1.0), RunResult("c", cost_usd=0.04)
                )
            )
    return out


def test_reports_show_paired_tests_against_the_cold_baseline() -> None:
    md = render_markdown(_records())
    assert "## Paired tests" in md
    row = next(line for line in md.splitlines() if line.startswith("| C vs A |"))
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[1] == "6"  # tasks
    assert cells[2] == "+100 pp" and cells[3] == "0.031"  # exact: 2/64
    assert cells[5] == "-0.0600" and cells[6] == "0.031"


def test_reports_show_bootstrap_intervals_per_condition() -> None:
    md = render_markdown(_records())
    assert "## Uncertainty" in md
    row = next(line for line in md.splitlines() if line.startswith("| C (95% CI) |"))
    assert "100% [100%, 100%]" in row


def test_break_even_says_when_cairn_pays_for_itself() -> None:
    md = render_markdown(_records())
    assert "Break-even" in md
    row = next(line for line in md.splitlines() if line.startswith("| C break-even |"))
    assert "saves $0.0600 per task (p = 0.031)" in row


def test_run_logs_load_back_and_combine(tmp_path: Path) -> None:
    log = tmp_path / "run.jsonl"
    log.write_text("".join(json.dumps(asdict(r)) + "\n" for r in _records()), encoding="utf-8")
    loaded = load_records(log)
    assert loaded == _records()
    combined = render_combined({"suite-x / sonnet": loaded, "suite-y / haiku": loaded[:4]})
    assert "## suite-x / sonnet" in combined and "## suite-y / haiku" in combined


def test_reports_are_plain_ascii_for_any_console() -> None:
    md = render_markdown(_records())
    assert md.isascii(), sorted({c for c in md if not c.isascii()})
