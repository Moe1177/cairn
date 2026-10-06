"""Markdown summary of a benchmark run: per-condition totals, then condition × task."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from statistics import fmean
from typing import TYPE_CHECKING

from cairn.bench.stats import bootstrap_ci, holm, wilcoxon

METRICS = ("success", "cost", "tokens")
SIGNIFICANCE = 0.05

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
    about = [f"{key}: {value}" for key, value in (meta or {}).items() if key != "tasks"]
    parts = [
        "# cairn benchmark",
        "",
        *([", ".join(about), ""] if about else []),
        CONDITIONS_LINE,
        "",
        *_body(records, level="##"),
        "",
        "## Per task",
        "",
        *_per_task(records),
        *_error_note(records),
    ]
    return "\n".join(parts) + "\n"


def render_combined(sections: Mapping[str, Sequence["RunRecord"]]) -> str:
    """One report over several runs (suite x model), each with its own statistics."""
    parts = ["# cairn benchmark (combined)", "", CONDITIONS_LINE, ""]
    for label, records in sections.items():
        parts += [f"## {label}", "", *_body(records, level="###"), *_error_note(records), ""]
    return "\n".join(parts).rstrip("\n") + "\n"


def load_records(path: Path) -> list["RunRecord"]:
    """Records from a run's `<stamp>.jsonl` log (one JSON object per finished run)."""
    from cairn.bench.grading import Grade
    from cairn.bench.run import RunRecord
    from cairn.bench.runner import RunResult

    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        if "_header" in raw:  # one per invocation: the settings, not a run
            continue
        result = dict(raw["result"])
        result["models"] = tuple(result.get("models", ()))
        records.append(
            RunRecord(
                raw["condition"],
                raw["task_id"],
                raw["run"],
                Grade(**raw["grade"]),
                RunResult(**result),
            )
        )
    return records


CONDITIONS_LINE = (
    "Conditions: A cold, B hand-written doc, C cairn INDEX, D INDEX + cards, E D + MCP"
)


def _body(records: Sequence["RunRecord"], *, level: str) -> list[str]:
    return [
        *_summary(records),
        "",
        f"{level} Uncertainty",
        "",
        "95% bootstrap intervals over tasks (each task's runs averaged first).",
        "",
        *_uncertainty(records),
        "",
        f"{level} Paired tests",
        "",
        "Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks). p is "
        "unadjusted; p adj is Holm-adjusted across this table's comparisons, per metric.",
        "",
        *_paired(records),
        "",
        f"{level} Break-even",
        "",
        "Per-task cost against the cold baseline. One-time costs are not counted: cairn's scan "
        "is local (seconds, no tokens), but the synthetic suites ship pre-written repo "
        "summaries whose /cairn authoring tokens are not counted, nor is the time to write "
        "condition B's doc.",
        "",
        *_break_even(records),
    ]


def _error_note(records: Sequence["RunRecord"]) -> list[str]:
    errors = sum(r.result.is_error for r in records)
    return (
        ["", f"{errors} run(s) ended in an agent error; see the JSON for details."]
        if errors
        else []
    )


def _task_means(records: Sequence["RunRecord"], condition: str, metric: str) -> dict[str, float]:
    """task id -> mean of `metric` over the task's runs. Success counts errored runs as
    failures; cost and tokens leave errored runs out (they report zeros)."""
    by_task: dict[str, list[float]] = {}
    for r in records:
        if r.condition != condition:
            continue
        if metric == "success":
            value = float(r.grade.success)
        elif r.result.is_error:
            continue
        else:
            value = float(r.result.cost_usd if metric == "cost" else r.result.fresh_tokens)
        by_task.setdefault(r.task_id, []).append(value)
    return {task: fmean(values) for task, values in by_task.items()}


def _conditions(records: Sequence["RunRecord"]) -> list[str]:
    return list(dict.fromkeys(r.condition for r in records))


def _uncertainty(records: Sequence["RunRecord"]) -> list[str]:
    lines = [
        "| Condition | Success | Cost per task (USD) | Fresh tokens |",
        "|---|---|---|---|",
    ]
    for condition in _conditions(records):
        success = list(_task_means(records, condition, "success").values())
        cost = list(_task_means(records, condition, "cost").values())
        tokens = list(_task_means(records, condition, "tokens").values())
        s_low, s_high = bootstrap_ci(success)
        c_low, c_high = bootstrap_ci(cost)
        t_low, t_high = bootstrap_ci(tokens)
        lines.append(
            f"| {condition} (95% CI) "
            f"| {_mean(success):.0%} [{s_low:.0%}, {s_high:.0%}] "
            f"| {_mean(cost):.4f} [{c_low:.4f}, {c_high:.4f}] "
            f"| {_mean(tokens):,.0f} [{t_low:,.0f}, {t_high:,.0f}] |"
        )
    return lines


def _paired(records: Sequence["RunRecord"]) -> list[str]:
    lines = [
        "| Comparison | Tasks | Success diff | p | p adj | Cost diff (USD) | p | p adj "
        "| Fresh-token diff | p | p adj |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    rows = []  # (label, n, [(delta, p) per metric])
    conditions = _conditions(records)
    for base in ("A", "B"):
        if base not in conditions:
            continue
        for condition in conditions:
            if condition == base or (base == "B" and condition == "A"):
                continue
            metrics = []
            n = 0
            for metric in METRICS:
                ours = _task_means(records, condition, metric)
                theirs = _task_means(records, base, metric)
                shared = sorted(set(ours) & set(theirs))
                x = [ours[t] for t in shared]
                y = [theirs[t] for t in shared]
                n = max(n, len(shared))
                metrics.append((_mean(x) - _mean(y), wilcoxon(x, y).p_value))
            rows.append((f"{condition} vs {base}", n, metrics))
    # Holm within each metric: every comparison in this table is one family.
    adjusted = [holm([row[2][m][1] for row in rows]) for m in range(len(METRICS))]
    for i, (label, n, metrics) in enumerate(rows):
        (d_s, p_s), (d_c, p_c), (d_t, p_t) = metrics
        a_s, a_c, a_t = (adjusted[m][i] for m in range(len(METRICS)))
        lines.append(
            f"| {label} | {n} | {d_s * 100:+.0f} pp | {p_s:.3f} | {a_s:.3f} "
            f"| {d_c:+.4f} | {p_c:.3f} | {a_c:.3f} | {d_t:+,.0f} | {p_t:.3f} | {a_t:.3f} |"
        )
    return lines


def _break_even(records: Sequence["RunRecord"]) -> list[str]:
    lines = ["| Condition | Per task vs A |", "|---|---|"]
    conditions = _conditions(records)
    if "A" not in conditions:
        return lines
    cold = _task_means(records, "A", "cost")
    for condition in conditions:
        if condition == "A":
            continue
        ours = _task_means(records, condition, "cost")
        shared = sorted(set(ours) & set(cold))
        if not shared:
            continue
        x = [ours[t] for t in shared]
        y = [cold[t] for t in shared]
        delta = _mean(x) - _mean(y)
        p = wilcoxon(x, y).p_value
        evidence = f"p = {p:.3f}" + ("" if p < SIGNIFICANCE else ", not significant")
        verdict = (
            f"saves ${-delta:.4f} per task ({evidence})"
            if delta < 0
            else f"costs ${delta:.4f} more per task ({evidence})"
        )
        note = " (the doc's writing time is not counted)" if condition == "B" else ""
        lines.append(f"| {condition} break-even | {verdict}{note} |")
    return lines
