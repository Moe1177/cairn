"""Run a benchmark suite across conditions and write a report (spec §11 E2)."""

import json
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import cairn
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
    meta: Mapping[str, object] | None = None,
) -> tuple[RunRecord, ...]:
    """Each finished run is appended to `<now>.jsonl` at once, so an interrupted (paid)
    benchmark keeps what it already measured; `<now>.json` and `.md` are written at the end."""
    suite = load_suite(suite_dir)
    tasks = [t for t in suite.tasks if not task_ids or t.id in task_ids]
    header = {
        "cairn_version": cairn.__version__,
        "suite": suite.name,
        "conditions": list(conditions),
        "runs": runs,
        "tasks": [t.id for t in tasks],
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        **(meta or {}),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    log = out_dir / f"{now}.jsonl"
    records: list[RunRecord] = []
    for condition in conditions:
        for task in tasks:
            for index in range(runs):
                # The MCP server of condition E may still hold files for a moment on Windows.
                with tempfile.TemporaryDirectory(
                    prefix="cairn-bench-", ignore_cleanup_errors=True
                ) as tmp:
                    prepared = prepare(condition, suite, suite_dir, Path(tmp))
                    ws = prepared.ws
                    repo_ids = {p.name for p in ws.iterdir() if (p / ".git").exists()}
                    result = runner.run(task.prompt, ws / task.repo, ws, prepared.mcp_config)
                    graded = grade(task, result.result_text, ws, repo_ids)
                record = RunRecord(condition, task.id, index, graded, result)
                records.append(record)
                with log.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(asdict(record)) + "\n")
    out = tuple(records)
    report = {"meta": header, "records": [asdict(r) for r in out]}
    atomic_write_text(out_dir / f"{now}.json", json.dumps(report, indent=2))
    atomic_write_text(out_dir / f"{now}.md", render_markdown(out, meta=header))
    return out
