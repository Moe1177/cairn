"""Run a benchmark suite across conditions and write a report (spec §11 E2)."""

import json
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import cairn
from cairn.bench.conditions import prepare
from cairn.bench.grading import Grade, grade
from cairn.bench.report import load_records, render_markdown
from cairn.bench.runner import Runner, RunResult
from cairn.bench.sources import fetch_sources
from cairn.bench.suite import load_suite
from cairn.errors import CairnError
from cairn.store.atomic import atomic_write_text

__all__ = ["BenchStopped", "RunRecord", "render_markdown", "run_bench"]


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
    resume: Path | None = None,
) -> tuple[RunRecord, ...]:
    """Each finished run is appended to `<now>.jsonl` at once, so an interrupted (paid)
    benchmark keeps what it already measured; `<now>.json` and `.md` are written at the end.

    A usage limit stops the run (BenchStopped) without recording the failed attempt. `resume`
    continues an earlier log: cells with a good run are kept, missing or failed ones run again.
    """
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
    source = fetch_sources(suite_dir, suite)  # an OSS suite's repos, fetched once
    log = resume or out_dir / f"{now}.jsonl"
    stem = log.with_suffix("")
    settings = {
        "suite": suite.name,
        "model": header.get("model"),
        "runs": runs,
        "conditions": list(conditions),
    }
    if resume is not None:
        _check_same_settings(resume, settings)
    # Every invocation leaves a header line, so a log says which settings and tools made it.
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"_header": header}) + "\n")
    done = {
        (r.condition, r.task_id, r.run): r
        for r in (load_records(resume) if resume else [])
        if not usage_limit(r.result)  # a genuine agent error is a result: it stands
    }
    records: list[RunRecord] = []
    for condition in conditions:
        for task in tasks:
            for index in range(runs):
                if (condition, task.id, index) in done:
                    records.append(done[(condition, task.id, index)])
                    continue
                # The MCP server of condition E may still hold files for a moment on Windows.
                with tempfile.TemporaryDirectory(
                    prefix="cairn-bench-", ignore_cleanup_errors=True
                ) as tmp:
                    prepared = prepare(condition, suite, suite_dir, Path(tmp), source)
                    ws = prepared.ws
                    repo_ids = {p.name for p in ws.iterdir() if (p / ".git").exists()}
                    result = runner.run(task.prompt, ws / task.repo, ws, prepared.mcp_config)
                    if usage_limit(result):
                        raise BenchStopped(
                            f"stopped: {result.result_text.strip()[:200]}. Measured runs are in "
                            f"{log}; continue later with `--resume {log}`."
                        )
                    graded = grade(task, result.result_text, ws, repo_ids)
                record = RunRecord(condition, task.id, index, graded, result)
                records.append(record)
                with log.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(asdict(record)) + "\n")
    out = tuple(records)
    report = {"meta": header, "records": [asdict(r) for r in out]}
    atomic_write_text(stem.with_suffix(".json"), json.dumps(report, indent=2))
    atomic_write_text(stem.with_suffix(".md"), render_markdown(out, meta=header))
    return out


def _check_same_settings(log: Path, settings: Mapping[str, object]) -> None:
    """Refuse to resume a log made with another model, suite, run count or conditions."""
    for line in log.read_text(encoding="utf-8").splitlines():
        if not line.startswith('{"_header"'):
            continue
        earlier = json.loads(line)["_header"]
        for key, value in settings.items():
            if key in earlier and earlier[key] != value:
                raise CairnError(
                    f"{log} was made with {key} {earlier[key]!r}, not {value!r}: resume it with "
                    f"the same --model, --runs and --conditions, or start a new run."
                )


class BenchStopped(CairnError):
    """A usage or rate limit: going on would only record failures."""


_LIMIT = re.compile(r"(?i)(?:session|usage|rate|weekly) limit|hit your \w+ limit")


def usage_limit(result: RunResult) -> bool:
    """An attempt stopped by a plan or rate limit (not a result)."""
    return result.is_error and _LIMIT.search(result.result_text) is not None
