"""The offline prior-art benchmark: an org's existing implementation of a feature, over the API."""

import json
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cairn.bench.prior_art import (
    Found,
    PriorArtQuery,
    PriorArtSet,
    evaluate,
    judged_at_5,
    key_problems,
    load_prior_art_set,
    load_terms,
    parse_terms,
    report,
    search_terms,
    write_terms,
)
from cairn.cli import app
from cairn.errors import CairnError
from cairn.remote.github import CodeHit, SearchPage

KEY = """\
org: acme
split: dev
queries:
  - id: limiter
    category: vocabulary
    task: Stop one client from flooding our API
    answers: [gateway/src/limiter.py, edge/rate.ts]
    rejected: [slack/pace.js]
  - id: stripe
    category: literal
    task: Verify Stripe webhook signatures
    answers: [pay/webhook.py]
"""
SUITE = Path(__file__).resolve().parents[1] / "bench" / "suites" / "aws-samples"


class FakeGitHub:
    def __init__(
        self, hits: dict[str, list[tuple[str, str]]], missing: frozenset[str] = frozenset()
    ) -> None:
        self.hits = hits
        self.missing = missing
        self.queries: list[str] = []

    def search_code(self, query: str, *, per_page: int = 10) -> SearchPage:
        self.queries.append(query)
        words = query.rsplit(" org:", 1)[0]
        found = next((v for k, v in self.hits.items() if k in words), [])
        hits = tuple(CodeHit(repo, path, ("match",)) for repo, path in found[:per_page])
        return SearchPage(hits, len(found), ms=12.0, waited=0.5)

    def file_exists(self, repo: str, path: str) -> bool:
        return f"{repo}/{path}" not in self.missing


def key(tmp_path: Path, text: str = KEY) -> PriorArtSet:
    (tmp_path / "prior_art.yaml").write_text(text, encoding="utf-8")
    return load_prior_art_set(tmp_path)


def test_rank_recall_and_judging(tmp_path: Path) -> None:
    pset = key(tmp_path)
    client = FakeGitHub(
        {
            "flooding": [
                ("acme/slack", "pace.js"),
                ("acme/other", "x.py"),
                ("acme/gateway", "src/limiter.py"),
            ],
            "Stripe": [("someone/fork", "pay/webhook.py")],
        }
    )
    outcomes = evaluate(client, pset, ["search-raw"])  # type: ignore[arg-type]
    limiter, stripe = outcomes
    assert limiter.rank == 3 and limiter.recall_at_5 == 0.5
    assert limiter.top == ("slack/pace.js", "other/x.py", "gateway/src/limiter.py")
    assert limiter.unjudged == ("other/x.py",)
    assert judged_at_5(limiter) == pytest.approx(2 / 3)
    assert limiter.searches == 1 and limiter.waited == 0.5
    # A hit outside the org keeps its owner, so it can't pass for the org's own file.
    assert stripe.rank is None and stripe.top == ("someone/fork/pay/webhook.py",)
    assert client.queries[0] == "Stop one client from flooding our API org:acme"


def test_nothing_found_is_fully_judged(tmp_path: Path) -> None:
    pset = key(tmp_path)
    outcome = evaluate(FakeGitHub({}), pset, ["search-terms"])[0]  # type: ignore[arg-type]
    assert outcome.rank is None and outcome.top == () and judged_at_5(outcome) == 1.0


def test_search_terms_keeps_a_few_task_words(tmp_path: Path) -> None:
    pset = key(tmp_path)
    client = FakeGitHub({})
    found = search_terms(client, pset, pset.queries[1], 10, ())  # type: ignore[arg-type]
    assert isinstance(found, Found) and found.searches == 1
    words = client.queries[0].removesuffix(" org:acme").split()
    assert 1 <= len(words) <= 3 and "stripe" in [w.lower() for w in words]


def test_key_problems_name_missing_answers(tmp_path: Path) -> None:
    pset = key(tmp_path)
    client = FakeGitHub({}, missing=frozenset({"acme/pay/webhook.py"}))
    assert key_problems(client, pset) == ["stripe: no file pay/webhook.py in acme"]  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "bad",
    [
        KEY.replace("[pay/webhook.py]", "[]"),
        KEY.replace("[pay/webhook.py]", "[/abs.py]"),
        KEY.replace("[pay/webhook.py]", "[pay/../../x.py]"),
        KEY.replace("category: literal", "category: chain"),
    ],
)
def test_invalid_keys_are_refused(tmp_path: Path, bad: str) -> None:
    with pytest.raises(CairnError, match="invalid prior-art key"):
        key(tmp_path, bad)


def test_report_has_the_tables(tmp_path: Path) -> None:
    pset = key(tmp_path)
    client = FakeGitHub({"flooding": [("acme/other", "x.py")]})
    text = report(evaluate(client, pset, ["search-raw"]))  # type: ignore[arg-type]
    assert "| dev | search-raw | vocabulary | 1 |" in text
    assert "| dev | search-raw | 0.50 | 1.0 | 1 |" in text  # judged@5, searches, waits
    assert "1 hits in a top five are unjudged" in text


def test_shipped_key_is_valid() -> None:
    pset = load_prior_art_set(SUITE)
    assert pset.org == "aws-samples" and len(pset.queries) >= 15
    assert len({q.id for q in pset.queries}) == len(pset.queries)
    assert {q.category for q in pset.queries} == {"literal", "vocabulary"}


def test_cli_writes_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key(tmp_path)
    client = FakeGitHub({"flooding": [("acme/gateway", "src/limiter.py")]})
    monkeypatch.setattr("cairn.remote.auth.github_token", lambda host: "tok")
    monkeypatch.setattr("cairn.remote.github.GitHub", lambda token, host: client)
    out = tmp_path / "out"
    result = CliRunner().invoke(
        app, ["bench-prior-art", str(tmp_path), "--locators", "search-raw", "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert "| dev | search-raw | vocabulary | 1 | 1.00 |" in result.output
    data = json.loads(next(out.glob("prior-art-*.json")).read_text(encoding="utf-8"))
    assert data[0]["query_id"] == "limiter" and data[0]["top"] == ["gateway/src/limiter.py"]


def test_cli_stops_on_a_stale_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key(tmp_path)
    client = FakeGitHub({}, missing=frozenset({"acme/pay/webhook.py"}))
    monkeypatch.setattr("cairn.remote.auth.github_token", lambda host: "tok")
    monkeypatch.setattr("cairn.remote.github.GitHub", lambda token, host: client)
    result = CliRunner().invoke(app, ["bench-prior-art", str(tmp_path)])
    assert result.exit_code == 1 and "no file pay/webhook.py" in result.output
    assert client.queries == []  # nothing is scored against a key that doesn't match


def test_cli_refuses_unknown_locators(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["bench-prior-art", str(tmp_path), "--locators", "magic"])
    assert result.exit_code == 1 and "unknown locator" in result.output


def test_query_paths_are_checked() -> None:
    with pytest.raises(ValueError):
        PriorArtQuery(id="x", category="literal", task="t", answers=("nofolder",))


def test_ms_leaves_out_rate_limit_waits(tmp_path: Path) -> None:
    pset = key(tmp_path)

    def slow(
        client: object, pset: PriorArtSet, query: PriorArtQuery, limit: int, terms: tuple
    ) -> Found:
        time.sleep(0.06)  # 60 ms, of which a 50 ms rate-limit wait
        return Found(("gateway/src/limiter.py",), "", searches=1, waited=0.05)

    outcome = evaluate(FakeGitHub({}), pset, ["slow"], registry={"slow": slow})[0]  # type: ignore[arg-type]
    assert 5 <= outcome.ms < 50 and outcome.waited == 0.05


@pytest.mark.parametrize("org", ["acme repo:evil/x", "-acme", "a" * 40, ""])
def test_org_names_are_checked(tmp_path: Path, org: str) -> None:
    with pytest.raises(CairnError, match="org must be"):
        key(tmp_path, KEY.replace("org: acme", f"org: '{org}'"))


def test_a_moved_repo_is_a_key_problem(tmp_path: Path) -> None:
    pset = key(tmp_path)

    class Moved(FakeGitHub):
        def file_exists(self, repo: str, path: str) -> bool:
            if repo == "acme/pay":
                raise CairnError("acme/pay has moved (renamed or transferred): update the key")
            return True

    assert key_problems(Moved({}), pset) == [  # type: ignore[arg-type]
        "stripe: acme/pay has moved (renamed or transferred): update the key"
    ]


def test_cli_reports_what_it_scored_before_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key(tmp_path)

    class FailsLate(FakeGitHub):
        def search_code(self, query: str, *, per_page: int = 10) -> SearchPage:
            if "Stripe" in query:
                raise CairnError("GitHub answered 503: busy")
            return super().search_code(query, per_page=per_page)

    client = FailsLate({"flooding": [("acme/gateway", "src/limiter.py")]})
    monkeypatch.setattr("cairn.remote.auth.github_token", lambda host: "tok")
    monkeypatch.setattr("cairn.remote.github.GitHub", lambda token, host: client)
    out = tmp_path / "out"
    result = CliRunner().invoke(
        app, ["bench-prior-art", str(tmp_path), "--locators", "search-raw", "--out", str(out)]
    )
    assert result.exit_code == 1
    assert "503: busy" in result.output and "the 1 outcomes scored before it" in result.output
    data = json.loads(next(out.glob("prior-art-*.json")).read_text(encoding="utf-8"))
    assert [o["query_id"] for o in data] == ["limiter"]


@pytest.mark.parametrize(
    ("text", "terms"),
    [
        (
            "express-rate-limit\nX-RateLimit-Remaining\nTokenBucket",
            ("express-rate-limit", "X-RateLimit-Remaining", "TokenBucket"),
        ),
        (
            "Here are three queries:\n\n1. `constructEvent`\n- 'Stripe-Signature'\n* webhook",
            ("constructEvent", "Stripe-Signature", "webhook"),
        ),
        ("Sure! Queries:\nA\nA\nB\nC\nD", ("A", "B", "C")),
        ("sure-thing\nSurely", ("sure-thing", "Surely")),
    ],
)
def test_parse_terms_drops_preambles_and_list_marks(text: str, terms: tuple[str, ...]) -> None:
    assert parse_terms(text) == terms


def test_write_terms_asks_only_for_missing_tasks(tmp_path: Path) -> None:
    pset = key(tmp_path)
    asked: list[str] = []

    def ask(task: str) -> tuple[str, ...]:
        asked.append(task)
        return ("RateLimiter",) if "flooding" in task else ("constructEvent",)

    first = write_terms(tmp_path, pset, ask, today="2026-10-17")
    assert first == {"limiter": ("RateLimiter",), "stripe": ("constructEvent",)}
    assert load_terms(tmp_path) == first
    text = (tmp_path / "agent_terms.yaml").read_text(encoding="utf-8")
    assert "never edited by hand" in text and "generated: '2026-10-17'" in text
    assert write_terms(tmp_path, pset, ask) == first and len(asked) == 2  # nothing asked again


def test_invalid_terms_file_is_refused(tmp_path: Path) -> None:
    (tmp_path / "agent_terms.yaml").write_text("terms: 3\n", encoding="utf-8")
    with pytest.raises(CairnError, match="invalid agent terms"):
        load_terms(tmp_path)


def test_cairn_locator_uses_the_agent_terms(tmp_path: Path) -> None:
    pset = key(tmp_path)
    client = FakeGitHub({"RateLimiter": [("acme/gateway", "src/limiter.py")]})
    terms = {"limiter": ("RateLimiter",)}
    outcomes = evaluate(client, pset, ["cairn"], terms=terms)  # type: ignore[arg-type]
    limiter = next(o for o in outcomes if o.query_id == "limiter")
    assert limiter.rank == 1 and limiter.searches == 1
    assert "RateLimiter org:acme" in client.queries
