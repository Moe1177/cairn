"""The offline link benchmark: real links found, and links found that aren't real."""

import json
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from cairn.bench.links_eval import (
    LinkSet,
    evaluate,
    key_problems,
    load_link_set,
    score,
    summarize,
)
from cairn.bench.locate_eval import prepare_workspace
from cairn.cli import app
from cairn.errors import CairnError
from cairn.model.graph import Confidence, Edge, EdgeType

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _edge(source: str, target: str, type_: EdgeType, confidence: Confidence) -> Edge:
    return Edge(source=source, target=target, type=type_, confidence=confidence, score=0.5)


def _key(text: str) -> LinkSet:
    return LinkSet.model_validate(yaml.safe_load(text))


KEY = """\
split: held
links:
  - {from: web, to: api, kind: http}
  - {from: api, to: worker, kind: pubsub}
  - {from: web, to: ui, kind: package}
unsure:
  - {between: [api, billing], note: "only in one region"}
"""


def test_pairs_are_scored_whatever_their_edge_type() -> None:
    edges = [
        _edge("web", "api", EdgeType.CALLS_HTTP, Confidence.INFERRED),
        _edge("web", "api", EdgeType.MENTIONS, Confidence.INFERRED),  # same pair: one link
        _edge("worker", "api", EdgeType.PUBSUB, Confidence.INFERRED),  # pointing the wrong way
        _edge("api", "billing", EdgeType.CALLS_HTTP, Confidence.INFERRED),  # unsure: not counted
        _edge("web", "worker", EdgeType.SHARES_ENV, Confidence.INFERRED),  # not a real link
    ]
    result = score("s", _key(KEY), edges, view="shown")
    assert (result.truth, result.predicted, result.hits) == (3, 3, 2)
    assert result.precision == pytest.approx(2 / 3) and result.recall == pytest.approx(2 / 3)
    assert result.direction == 0.5  # web -> api right, worker -> api wrong
    assert result.wrong_direction == ("api -> worker (pubsub); cairn: worker -> api (pubsub)",)
    assert result.false_positives == ("web ~ worker (shares_env inferred)",)
    assert result.false_negatives == ("web -> ui (package)",)
    assert result.recall_by_kind == (("http", 1, 1), ("pubsub", 1, 1), ("package", 0, 1))


@pytest.mark.parametrize("type_", [EdgeType.SHARES_DB, EdgeType.MENTIONS])
def test_a_shared_database_or_a_doc_mention_has_no_wrong_direction(type_: EdgeType) -> None:
    key = _key("split: dev\nlinks:\n  - {from: a, to: b, kind: database}\n")
    result = score("s", key, [_edge("b", "a", type_, Confidence.INFERRED)], view="all")
    assert result.direction == 1.0 and result.wrong_direction == ()


def test_nothing_predicted_and_nothing_true_score_as_perfect() -> None:
    result = score("s", _key("split: dev\nlinks: []\n"), [], view="shown")
    assert (result.precision, result.recall, result.f1, result.direction) == (1.0, 1.0, 1.0, 1.0)


def test_a_key_is_validated(tmp_path: Path) -> None:
    (tmp_path / "links.yaml").write_text(KEY, encoding="utf-8")
    assert [link.target for link in load_link_set(tmp_path).links] == ["api", "worker", "ui"]
    for bad in (
        "split: dev\nlinks:\n  - {from: a, to: b, kind: vibes}\n",
        "split: dev\nlinks:\n  - {from: a, to: a, kind: http}\n",
        "split: later\nlinks: []\n",
    ):
        (tmp_path / "links.yaml").write_text(bad, encoding="utf-8")
        with pytest.raises(CairnError):
            load_link_set(tmp_path)


def test_a_key_must_name_repos_that_exist_once_each() -> None:
    key = _key(KEY)
    assert key_problems(["web", "api", "worker", "ui", "billing"], key) == []
    assert key_problems(["web", "api", "worker"], key) == ["no repo ui", "no repo billing"]
    twice = _key(
        "split: dev\nlinks:\n  - {from: a, to: b, kind: http}\n  - {from: b, to: a, kind: docs}\n"
    )
    assert key_problems(["a", "b"], twice) == ["listed twice: a ~ b"]


def _microshop_suite(tmp_path: Path, links: list[dict]) -> Path:
    suite = tmp_path / "suite"
    shutil.copytree(FIXTURES / "workspaces" / "microshop", suite / "fixtures")
    (suite / "suite.yaml").write_text(
        "name: micro\nworkspace: fixtures\nrelated_repos_doc: r.md\ntasks: []\n", encoding="utf-8"
    )
    (suite / "links.yaml").write_text(
        yaml.safe_dump({"split": "dev", "links": links}), encoding="utf-8"
    )
    return suite


def _expected_microshop() -> list[dict]:
    expected = yaml.safe_load((FIXTURES / "expectations" / "microshop.yaml").read_text("utf-8"))
    kinds = {"calls_http": "http", "pubsub": "pubsub", "deploys": "deploys"}
    return [{"from": e["from"], "to": e["to"], "kind": kinds[e["type"]]} for e in expected["edges"]]


def test_a_real_scan_is_scored_against_its_key(tmp_path: Path) -> None:
    links = _expected_microshop()
    missed = {"from": "ops-tools", "to": "payments", "kind": "http"}
    suite = _microshop_suite(tmp_path, [*links[1:], missed])
    ws = prepare_workspace(suite, tmp_path / "cache")
    shown, everything = evaluate(ws, "micro", load_link_set(suite))
    assert shown.view == "shown" and everything.view == "all"
    assert shown.truth == len(links) and shown.hits == len(links) - 1
    assert shown.false_negatives == ("ops-tools -> payments (http)",)
    first = links[0]
    assert shown.false_positives == (
        f"{min(first['from'], first['to'])} ~ {max(first['from'], first['to'])} (calls_http inferred)",
    )
    assert shown.direction == 1.0
    text = summarize([shown, everything])
    assert "| dev | micro | shown |" in text and "Missed:\n- ops-tools -> payments (http)" in text


def test_a_key_naming_an_unknown_repo_stops_the_run(tmp_path: Path) -> None:
    suite = _microshop_suite(tmp_path, [{"from": "storefront", "to": "ghost", "kind": "http"}])
    ws = prepare_workspace(suite, tmp_path / "cache")
    with pytest.raises(CairnError, match="no repo ghost"):
        evaluate(ws, "micro", load_link_set(suite))


def test_the_cli_writes_a_report(tmp_path: Path) -> None:
    suite = _microshop_suite(tmp_path, _expected_microshop())
    out = tmp_path / "out"
    result = CliRunner().invoke(
        app, ["bench-links", str(suite), "--cache", str(tmp_path / "c"), "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert "| dev | suite | shown | 12 | 12 | 1.00 | 1.00 | 1.00 | 1.00 |" in result.output
    rows = json.loads(next(out.glob("links-*.json")).read_text(encoding="utf-8"))
    assert [r["view"] for r in rows] == ["shown", "all"] and rows[0]["recall"] == 1.0
