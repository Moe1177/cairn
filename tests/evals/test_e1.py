"""E1: deterministic map-quality gates (spec §11). These run in CI on every commit."""

import os
import re
from pathlib import Path

import pytest
import yaml

from cairn.emit import write_outputs
from cairn.integrations.claude import install_claude
from cairn.load import load_authored
from cairn.render.index import INDEX_TITLE
from cairn.render.tokens import estimate_tokens
from cairn.resolve import resolve_repo
from cairn.scan import scan_workspace
from tests.evals.metrics import check_faithfulness, edge_metrics

EXPECTATIONS = Path(__file__).resolve().parents[2] / "fixtures" / "expectations"
GOLDEN = Path(__file__).resolve().parent / "golden"
REMOTE_TOKEN = "ghp_REMOTEFAKEfakeFAKEfake1234567890"
REMOTES = {
    "mini-eats": {"eats": f"https://bot:{REMOTE_TOKEN}@github.com/acme/eats.git"},
    "polyglot": {},
    "lookalikes": {},
}
SECRETS = ("sk_live_FAKE", "sk_test_FAKEreadme", "SuperSecretPw123", "ghp_FAKEfake", REMOTE_TOKEN)


def _expect(name: str) -> dict:
    return yaml.safe_load((EXPECTATIONS / f"{name}.yaml").read_text(encoding="utf-8"))


def _scan(materialize, name: str):
    ws = materialize(name, remotes=REMOTES[name]).resolve()
    result = scan_workspace(ws)
    write_outputs(ws, result)
    return ws, result


def test_edge_detection_meets_calibration_gates(materialize) -> None:
    predicted, expected = [], []
    for name in REMOTES:
        _, result = _scan(materialize, name)
        predicted += [
            (e.source, e.target, e.type.value, e.confidence.value) for e in result.workspace.edges
        ]
        expected += [
            (e["from"], e["to"], e["type"], e["confidence"]) for e in _expect(name)["edges"]
        ]
    metrics = edge_metrics(predicted, expected)
    assert metrics.recall >= 0.85, metrics.describe()
    assert metrics.extracted_precision >= 0.95, metrics.describe()
    assert metrics.inferred_precision >= 0.80, metrics.describe()
    assert metrics.tier_accuracy >= 0.90, metrics.describe()


def test_resolution_accuracy(materialize) -> None:
    total = top1 = top3 = 0
    misses = []
    for name in REMOTES:
        ws, result = _scan(materialize, name)
        authored = load_authored(ws)
        for case in _expect(name)["phrasings"]:
            ids = [m.repo_id for m in resolve_repo(result.workspace, authored, case["query"])]
            total += 1
            top1 += ids[:1] == [case["repo"]]
            top3 += case["repo"] in ids[:3]
            if ids[:1] != [case["repo"]]:
                misses.append(f"{case['query']!r}: expected {case['repo']}, got {ids[:3]}")
    assert top1 / total >= 0.85, "\n".join(misses)
    assert top3 / total >= 0.95, "\n".join(misses)


def test_every_evidence_item_is_faithful(materialize) -> None:
    for name in REMOTES:
        ws, result = _scan(materialize, name)
        assert check_faithfulness(ws, result.workspace) == []


def test_cards_and_index_respect_budgets(materialize) -> None:
    for name in REMOTES:
        ws, result = _scan(materialize, name)
        for card in (ws / ".cairn" / "cards").glob("*.md"):
            assert estimate_tokens(card.read_text(encoding="utf-8")) <= result.config.card_budget, (
                card.name
            )
        index_lines = (ws / ".cairn" / "INDEX.md").read_text(encoding="utf-8").splitlines()
        repo_lines = [line for line in index_lines if line.startswith("- ")]
        assert (
            repo_lines and sum(estimate_tokens(line) for line in repo_lines) / len(repo_lines) <= 30
        )


def test_no_secret_ever_leaves_the_repo(materialize, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CAIRN_HOME", str(tmp_path / "home"))
    ws, _ = _scan(materialize, "mini-eats")
    install_claude(ws)
    outputs = [p for p in (ws / ".cairn").rglob("*") if p.is_file()]
    outputs += [ws / "CLAUDE.md", *(tmp_path / "home").rglob("*.json")]
    for path in outputs:
        text = path.read_text(encoding="utf-8", errors="replace")
        for secret in SECRETS:
            assert secret not in text, f"{secret} leaked into {path}"
    assert "[REDACTED]" in (ws / ".cairn" / "workspace.json").read_text(encoding="utf-8")


def _normalize(text: str, ws: Path) -> str:
    return re.sub(r"HEAD [0-9a-f]{7,}", "HEAD <sha>", text.replace(ws.as_posix(), "<WS>"))


@pytest.mark.parametrize("rel", ["INDEX.md", "cards/eats.md", "cards/eats-admin.md"])
def test_golden_outputs(materialize, rel: str) -> None:
    ws, _ = _scan(materialize, "mini-eats")
    actual = _normalize((ws / ".cairn" / rel).read_text(encoding="utf-8"), ws)
    golden = GOLDEN / "mini-eats" / rel
    if os.environ.get("CAIRN_UPDATE_GOLDEN") == "1":
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(actual, encoding="utf-8", newline="\n")
    assert actual.startswith(INDEX_TITLE) or actual.startswith("# ")
    assert golden.read_text(encoding="utf-8") == actual


def test_lookalikes_have_no_confident_false_positives(materialize) -> None:
    _, result = _scan(materialize, "lookalikes")
    # A confident edge is wrong if it is unexpected OR expected only as `ambiguous`.
    confident_ok = {
        (*sorted((e["from"], e["to"])), e["type"])
        for e in _expect("lookalikes")["edges"]
        if e["confidence"] != "ambiguous"
    }
    confident = [e for e in result.workspace.edges if e.confidence.value != "ambiguous"]
    wrong = [
        e.key
        for e in confident
        if (*sorted((e.source, e.target)), e.type.value) not in confident_ok
    ]
    assert wrong == []


def test_scan_never_opens_forbidden_files(materialize, monkeypatch) -> None:
    from cairn.security.policy import is_forbidden

    opened: list[Path] = []
    real_open = Path.open

    def spy(self: Path, *args, **kwargs):
        opened.append(self)
        return real_open(self, *args, **kwargs)

    ws = materialize("mini-eats", remotes=REMOTES["mini-eats"]).resolve()
    monkeypatch.setattr(Path, "open", spy)
    write_outputs(ws, scan_workspace(ws))
    assert opened and [p for p in opened if is_forbidden(p)] == []
