import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cairn.bench.run import render_markdown, run_bench
from cairn.bench.runner import FakeRunner
from cairn.cli import app

SUITE = Path(__file__).resolve().parents[1] / "bench" / "suites" / "shopverse"


def _reply(prompt: str, cwd: Path) -> str:
    answer = "storefront/lib/cart.ts" if "cart total" in prompt else "no idea"
    cost = 0.01 if (cwd.parent / "CLAUDE.md").exists() else 0.05
    usage = {"input_tokens": 1, "cache_creation_input_tokens": 100, "output_tokens": 9}
    return json.dumps({"result": answer, "num_turns": 2, "total_cost_usd": cost, "usage": usage})


def test_run_bench_with_fake_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAIRN_HOME", str(tmp_path / "ch"))
    monkeypatch.setenv("CAIRN_USER_HOME", str(tmp_path / "uh"))
    records = run_bench(
        SUITE,
        conditions=("A", "D"),
        runs=1,
        task_ids=("cart-total",),
        runner=FakeRunner(_reply),
        out_dir=tmp_path / "out",
        now="20261005-120000",
    )
    assert len(records) == 2 and all(r.grade.success for r in records)
    assert [r.result.cost_usd for r in records] == [0.05, 0.01]  # D has the CLAUDE.md index
    md = (tmp_path / "out" / "20261005-120000.md").read_text(encoding="utf-8")
    assert "| A |" in md and "| D |" in md and md == render_markdown(records)
    data = json.loads((tmp_path / "out" / "20261005-120000.json").read_text(encoding="utf-8"))
    assert data[0]["condition"] == "A" and data[0]["result"]["num_turns"] == 2


def test_bench_cli_rejects_unknown_condition_and_task(tmp_path: Path) -> None:
    runner = CliRunner()
    bad = runner.invoke(app, ["bench", str(SUITE), "--conditions", "A,Z"])
    assert bad.exit_code == 1 and "unknown condition" in bad.output
    bad = runner.invoke(app, ["bench", str(SUITE), "--tasks", "nope", "--out", str(tmp_path)])
    assert bad.exit_code == 1 and "unknown task" in bad.output
