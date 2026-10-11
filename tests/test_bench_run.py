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
    assert (
        "| A |" in md and "| D |" in md and render_markdown(records).split("Conditions:")[1] in md
    )
    data = json.loads((tmp_path / "out" / "20261005-120000.json").read_text(encoding="utf-8"))
    first = data["records"][0]
    assert first["condition"] == "A" and first["result"]["num_turns"] == 2


def test_bench_cli_rejects_unknown_condition_and_task(tmp_path: Path) -> None:
    runner = CliRunner()
    bad = runner.invoke(app, ["bench", str(SUITE), "--conditions", "A,Z"])
    assert bad.exit_code == 1 and "unknown condition" in bad.output
    bad = runner.invoke(app, ["bench", str(SUITE), "--tasks", "nope", "--out", str(tmp_path)])
    assert bad.exit_code == 1 and "unknown task" in bad.output


def test_one_workspace_serves_every_condition_without_leaking_between_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 38-repo suite takes many minutes to copy into git repos: once per benchmark."""
    import cairn.bench.run as run_module

    monkeypatch.setenv("CAIRN_HOME", str(tmp_path / "ch"))
    monkeypatch.setenv("CAIRN_USER_HOME", str(tmp_path / "uh"))
    made: list[Path] = []
    real = run_module.make_workspace

    def counting(*args, **kwargs):
        made.append(real(*args, **kwargs))
        return made[-1]

    seen: dict[str, tuple[bool, str]] = {}

    def reply(prompt: str, cwd: Path) -> str:
        ws = cwd.parent
        claude = ws / "CLAUDE.md"
        text = claude.read_text(encoding="utf-8") if claude.is_file() else ""
        seen[condition_of(text, (ws / ".cairn").is_dir())] = ((ws / ".cairn").is_dir(), text[:20])
        return _reply(prompt, cwd)

    def condition_of(text: str, mapped: bool) -> str:
        if not text:
            return "A"
        return "D" if mapped else ("B" if "Related" in text or "related" in text else "C")

    monkeypatch.setattr(run_module, "make_workspace", counting)
    records = run_bench(
        SUITE,
        conditions=("D", "A", "B", "C"),
        runs=2,
        task_ids=("cart-total", "gift-message"),
        runner=FakeRunner(reply),
        out_dir=tmp_path / "out",
        now="20261005-120000",
    )
    assert len(made) == 1 and len(records) == 16
    assert sorted(seen) == ["A", "B", "C", "D"]
    assert seen["A"] == (False, "")  # after D: no map and no CLAUDE.md left behind
    assert not seen["B"][0] and not seen["C"][0]  # C: the index only, no cards to read
    assert [(r.condition, r.task_id, r.run) for r in records][:4] == [
        ("D", "gift-message", 0),  # the suite's order
        ("D", "gift-message", 1),
        ("D", "cart-total", 0),
        ("D", "cart-total", 1),
    ]


def test_regrade_grades_a_finished_log_again_against_a_fresh_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CAIRN_HOME", str(tmp_path / "ch"))
    monkeypatch.setenv("CAIRN_USER_HOME", str(tmp_path / "uh"))
    run_bench(
        SUITE,
        conditions=("A",),
        runs=1,
        task_ids=("cart-total",),
        runner=FakeRunner(_reply),
        out_dir=tmp_path / "out",
        now="20261011-120000",
    )
    log = tmp_path / "out" / "20261011-120000.jsonl"
    lines = log.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    # The run's workspace was a temp dir, gone now: its paths must still count.
    record["result"]["result_text"] = "C:\Temp\cairn-bench-x1\ws\storefront\lib\cart.ts"
    record["grade"] = {"success": False, "recall": 0.0, "precision": 0.0}
    log.write_text("\n".join([lines[0], json.dumps(record)]) + "\n", encoding="utf-8")
    cache = tmp_path / "cache"
    result = CliRunner().invoke(app, ["bench-regrade", str(SUITE), str(log), "--cache", str(cache)])
    assert result.exit_code == 0, result.output
    data = json.loads(log.with_suffix(".json").read_text(encoding="utf-8"))
    assert data["records"][0]["grade"]["success"] and data["meta"]["regraded_with"]
    assert json.loads(log.read_text(encoding="utf-8").splitlines()[1])["grade"]["success"] is False
    missing = CliRunner().invoke(app, ["bench-regrade", str(SUITE), str(tmp_path / "nope.jsonl")])
    assert missing.exit_code == 1 and "no run log" in missing.output
