"""E1 metrics: edge precision/recall with calibration, and evidence faithfulness."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from cairn.model.graph import Workspace
from cairn.security.redact import make_snippet

EdgeTuple = tuple[str, str, str, str]  # source, target, type, confidence


def _key(source: str, target: str, type_: str) -> tuple[str, str, str]:
    a, b = sorted((source, target))
    return a, b, type_


@dataclass(frozen=True)
class EdgeMetrics:
    precision: float
    recall: float
    extracted_precision: float
    inferred_precision: float
    tier_accuracy: float
    false_positives: tuple[tuple[str, str, str], ...]
    false_negatives: tuple[tuple[str, str, str], ...]

    def describe(self) -> str:
        return (
            f"precision={self.precision:.2f} recall={self.recall:.2f} "
            f"extracted_precision={self.extracted_precision:.2f} inferred_precision={self.inferred_precision:.2f}\n"
            f"false positives: {list(self.false_positives)}\nfalse negatives: {list(self.false_negatives)}"
        )


def edge_metrics(predicted: Sequence[EdgeTuple], expected: Sequence[EdgeTuple]) -> EdgeMetrics:
    want = {_key(s, t, ty) for s, t, ty, _ in expected}
    got = {_key(s, t, ty): conf for s, t, ty, conf in predicted}
    hits = set(got) & want
    want_tier = {_key(s, t, ty): conf for s, t, ty, conf in expected}
    exact = sum(got.get(k) == conf for k, conf in want_tier.items())

    def tier(confidence: str) -> float:
        keys = [k for k, c in got.items() if c == confidence]
        return 1.0 if not keys else sum(k in want for k in keys) / len(keys)

    return EdgeMetrics(
        precision=len(hits) / len(got) if got else 1.0,
        recall=len(hits) / len(want) if want else 1.0,
        extracted_precision=tier("extracted"),
        inferred_precision=tier("inferred"),
        tier_accuracy=exact / len(want_tier) if want_tier else 1.0,
        false_positives=tuple(sorted(set(got) - want)),
        false_negatives=tuple(sorted(want - set(got))),
    )


def check_faithfulness(ws_root: Path, workspace: Workspace) -> list[str]:
    roots = {r.id: ws_root / r.path for r in workspace.repos}
    evidence = [
        ev
        for r in workspace.repos
        for f in (*r.contracts.exposes, *r.contracts.consumes)
        for ev in f.evidence
    ]
    evidence += [ev for e in workspace.edges for ev in e.evidence]
    problems = []
    for ev in evidence:
        path = roots[ev.repo] / ev.file
        if not path.is_file():
            problems.append(f"missing file: {ev.repo}/{ev.file}")
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if ev.line > len(lines):
            problems.append(f"line out of range: {ev.repo}/{ev.file}:{ev.line}")
        elif ev.snippet and make_snippet(lines[ev.line - 1]) != ev.snippet:
            # An empty snippet is deliberately withheld (SQL seed rows, env templates).
            problems.append(f"snippet mismatch: {ev.repo}/{ev.file}:{ev.line}")
    return problems
