"""Markdown summary of a benchmark run: per-condition totals, then condition × task."""

from collections.abc import Mapping, Sequence
from statistics import fmean
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cairn.bench.run import RunRecord


def _mean(values: Sequence[float]) -> float:
    return fmean(values) if values else 0.0


def _summary(records: Sequence["RunRecord"]) -> list[str]:
    """Success counts every run; token/cost/turn means use only runs that didn't error,
    since an errored run reports zeros that would flatter its condition."""
    lines = [
        "| Condition | Runs | Success | Fresh tokens | Cache-read tokens | Cost (USD) | Turns "
        "| Errors |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for condition in dict.fromkeys(r.condition for r in records):
        rows = [r for r in records if r.condition == condition]
        ok = [r for r in rows if not r.result.is_error]
        success = sum(r.grade.success for r in rows) / len(rows)
        lines.append(
            f"| {condition} | {len(rows)} | {success:.0%} "
            f"| {_mean([r.result.fresh_tokens for r in ok]):,.0f} "
            f"| {_mean([r.result.cache_read_tokens for r in ok]):,.0f} "
            f"| {_mean([r.result.cost_usd for r in ok]):.4f} "
            f"| {_mean([r.result.num_turns for r in ok]):.1f} "
            f"| {len(rows) - len(ok)} |"
        )
    return lines


def _per_task(records: Sequence["RunRecord"]) -> list[str]:
    lines = [
        "| Condition | Task | Success | Recall | Cost (USD) |",
        "|---|---|---|---|---|",
    ]
    for condition in dict.fromkeys(r.condition for r in records):
        for task_id in dict.fromkeys(r.task_id for r in records):
            rows = [r for r in records if r.condition == condition and r.task_id == task_id]
            if not rows:
                continue
            passed = sum(r.grade.success for r in rows)
            lines.append(
                f"| {condition} | {task_id} | {passed}/{len(rows)} "
                f"| {_mean([r.grade.recall for r in rows]):.2f} "
                f"| {_mean([r.result.cost_usd for r in rows if not r.result.is_error]):.4f} |"
            )
    return lines


def render_markdown(
    records: Sequence["RunRecord"], *, meta: Mapping[str, object] | None = None
) -> str:
    errors = sum(r.result.is_error for r in records)
    about = [f"{key}: {value}" for key, value in (meta or {}).items() if key != "tasks"]
    parts = [
        "# cairn benchmark",
        "",
        *([", ".join(about), ""] if about else []),
        "Conditions: A cold, B hand-written doc, C cairn INDEX, D INDEX + cards, E D + MCP",
        "",
        *_summary(records),
        "",
        "## Per task",
        "",
        *_per_task(records),
    ]
    if errors:
        parts += ["", f"{errors} run(s) ended in an agent error; see the JSON for details."]
    return "\n".join(parts) + "\n"
