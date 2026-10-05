"""Run a benchmark suite across conditions and write a report (spec §11 E2)."""

import json
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from cairn.bench.conditions import prepare
from cairn.bench.grading import Grade, grade
from cairn.bench.report import render_markdown
from cairn.bench.runner import Runner, RunResult
from cairn.bench.suite import load_suite
from cairn.store.atomic import atomic_write_text

__all__ = ["RunRecord", "render_markdown", "run_bench"]


@dataclass(frozen=True)
class RunRecord:
    condition: str
    task_id: str
    run: int
    grade: Grade
    result: RunResult


def run_bench(
    suite_dir: Path,
    *,
    conditions: Sequence[str],
    runs: int,
    task_ids: Sequence[str] | None,
    runner: Runner,
    out_dir: Path,
    now: str,
) -> tuple[RunRecord, ...]:
    suite = load_suite(suite_dir)
    tasks = [t for t in suite.tasks if not task_ids or t.id in task_ids]
    records: list[RunRecord] = []
    for condition in conditions:
        for task in tasks:
            for index in range(runs):
                with tempfile.TemporaryDirectory(prefix="cairn-bench-") as tmp:
                    prepared = prepare(condition, suite, suite_dir, Path(tmp))
                    ws = prepared.ws
                    repo_ids = {p.name for p in ws.iterdir() if (p / ".git").exists()}
                    result = runner.run(task.prompt, ws / task.repo, ws, prepared.mcp_config)
                    graded = grade(task, result.result_text, ws, repo_ids)
                    records.append(RunRecord(condition, task.id, index, graded, result))
    out = tuple(records)
    atomic_write_text(out_dir / f"{now}.json", json.dumps([asdict(r) for r in out], indent=2))
    atomic_write_text(out_dir / f"{now}.md", render_markdown(out))
    return out
