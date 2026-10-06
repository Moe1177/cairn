"""Combine benchmark run logs into one report with statistics (spec §11 E2/E3).

    uv run python bench/combine_results.py bench/results/lean --out report.md

Expects `<root>/<model>/<suite>/<stamp>.jsonl` (what `cairn bench --out <root>/<model>/<suite>`
writes). Sections: every model pooled over all suites (task ids prefixed by suite, so tasks
never collide), then each suite x model.
"""

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from cairn.bench.report import load_records, render_combined


def collect(root: Path) -> dict[str, list]:
    sections: dict[str, list] = {}
    pooled: dict[str, list] = {}
    for model_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for suite_dir in sorted(p for p in model_dir.iterdir() if p.is_dir()):
            logs = sorted(suite_dir.glob("*.jsonl"))
            if not logs:
                continue
            # The latest log of this suite x model. A resumed log also holds the attempts that
            # hit a usage limit: keep one record per cell, the good one when there is one.
            cells: dict = {}
            for record in load_records(logs[-1]):
                key = (record.condition, record.task_id, record.run)
                if key not in cells or cells[key].result.is_error:
                    cells[key] = record
            records = list(cells.values())
            sections[f"{suite_dir.name} / {model_dir.name}"] = records
            pooled.setdefault(model_dir.name, []).extend(
                replace(r, task_id=f"{suite_dir.name}:{r.task_id}") for r in records
            )
    return {
        **{f"All suites / {model}": records for model, records in pooled.items()},
        **sections,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Combine cairn benchmark run logs.")
    parser.add_argument("root", type=Path, help="results root: <root>/<model>/<suite>/")
    parser.add_argument("--out", type=Path, help="write the report here (default: stdout)")
    args = parser.parse_args(argv)
    report = render_combined(collect(args.root))
    if args.out:
        args.out.write_text(report, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
