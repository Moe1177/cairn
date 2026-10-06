"""Phase 4 Task 7: a benchmark stops at a usage limit and resumes without redoing good runs."""

import json
from pathlib import Path

import pytest

from cairn.bench.run import BenchStopped, run_bench
from cairn.bench.runner import FakeRunner

SUITE = Path(__file__).resolve().parents[1] / "bench" / "suites" / "shopverse"
LIMIT = "You've hit your session limit · resets 1:20am (America/Toronto)"


class _Scripted:
    """Answers normally for the first `ok` runs, then reports a usage limit."""

    def __init__(self, ok: int) -> None:
        self.ok, self.calls = ok, 0

    def __call__(self, prompt: str, cwd: Path) -> str:
        self.calls += 1
        if self.calls > self.ok:
            return json.dumps({"result": LIMIT, "is_error": True, "total_cost_usd": 0})
        usage = {"input_tokens": 1, "output_tokens": 1}
        return json.dumps({"result": "x", "num_turns": 1, "total_cost_usd": 0.01, "usage": usage})


def _run(tmp_path: Path, reply, **kwargs):  # type: ignore[no-untyped-def]
    return run_bench(
        SUITE,
        conditions=("A", "C"),
        runs=2,
        task_ids=("cart-total",),
        runner=FakeRunner(reply),
        out_dir=tmp_path / "out",
        now="20261006-010000",
        **kwargs,
    )


def test_a_usage_limit_stops_the_run_and_keeps_the_good_ones(tmp_path: Path) -> None:
    reply = _Scripted(ok=2)
    with pytest.raises(BenchStopped, match="--resume"):
        _run(tmp_path, reply)
    assert reply.calls == 3  # stopped at the first limit, not after every remaining cell
    log = tmp_path / "out" / "20261006-010000.jsonl"
    lines = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 2 and not any(r["result"]["is_error"] for r in lines)


def test_resume_runs_only_the_missing_or_failed_cells(tmp_path: Path) -> None:
    with pytest.raises(BenchStopped):
        _run(tmp_path, _Scripted(ok=2))
    log = tmp_path / "out" / "20261006-010000.jsonl"
    # An older log may also hold limit errors: those cells run again too.
    failed = {
        "condition": "C",
        "task_id": "cart-total",
        "run": 0,
        "grade": {"success": False, "recall": 0.0, "precision": 0.0},
        "result": {"result_text": LIMIT, "is_error": True},
    }
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(failed) + "\n")
    reply = _Scripted(ok=99)
    records = _run(tmp_path, reply, resume=log)
    assert reply.calls == 2  # C run 0 and C run 1; A's two runs were already good
    assert len(records) == 4 and not any(r.result.is_error for r in records)
    assert sorted((r.condition, r.run) for r in records) == [("A", 0), ("A", 1), ("C", 0), ("C", 1)]
