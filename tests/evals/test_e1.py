"""E1: deterministic map-quality gates (spec §11). These run in CI on every commit."""

import os
import re
from pathlib import Path

import pytest
import yaml

from cairn.bench.workspace import materialize as materialize_tree
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
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "workspaces"
REMOTE_TOKEN = "ghp_REMOTEFAKEfakeFAKEfake1234567890"
REMOTES = {
    "mini-eats": {"eats": f"https://bot:{REMOTE_TOKEN}@github.com/acme/eats.git"},
    "polyglot": {},
    "lookalikes": {},
    "servicemesh": {},
    "microshop": {},
    "eventsuite": {},
    "cloudshop": {},
    "railyard": {},
    "flyway": {},
}
SECRETS = ("sk_live_FAKE", "sk_test_FAKEreadme", "SuperSecretPw123", "ghp_FAKEfake", REMOTE_TOKEN)


def _expect(name: str) -> dict:
    return yaml.safe_load((EXPECTATIONS / f"{name}.yaml").read_text(encoding="utf-8"))


def _scan(materialize, name: str):
    ws = materialize(name, remotes=REMOTES[name]).resolve()
    result = scan_workspace(ws)
    write_outputs(ws, result)
    return ws, result


@pytest.fixture(scope="session")
def scanned(tmp_path_factory: pytest.TempPathFactory):
    """One scan per workspace for the evals that only read it (each xdist worker has its own)."""
    cache: dict[str, tuple] = {}

    def _get(name: str):
        if name not in cache:
            dest = tmp_path_factory.mktemp("e1") / name
            ws = materialize_tree(FIXTURES / name, dest, remotes=REMOTES[name]).resolve()
            result = scan_workspace(ws)
            write_outputs(ws, result)
            cache[name] = (ws, result)
        return cache[name]

    return _get


def test_edge_detection_meets_calibration_gates(scanned) -> None:
    predicted, expected = [], []
    for name in REMOTES:
        _, result = scanned(name)
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


def test_resolution_accuracy(scanned) -> None:
    total = top1 = top3 = 0
    misses = []
    for name in REMOTES:
        ws, result = scanned(name)
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


def test_every_evidence_item_is_faithful(scanned) -> None:
    for name in REMOTES:
        ws, result = scanned(name)
        assert check_faithfulness(ws, result.workspace) == []


def test_cards_and_index_respect_budgets(scanned) -> None:
    for name in REMOTES:
        ws, result = scanned(name)
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
def test_golden_outputs(scanned, rel: str) -> None:
    ws, _ = scanned("mini-eats")
    actual = _normalize((ws / ".cairn" / rel).read_text(encoding="utf-8"), ws)
    golden = GOLDEN / "mini-eats" / rel
    if os.environ.get("CAIRN_UPDATE_GOLDEN") == "1":
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(actual, encoding="utf-8", newline="\n")
    assert actual.startswith(INDEX_TITLE) or actual.startswith("# ")
    assert golden.read_text(encoding="utf-8") == actual


def test_lookalikes_have_no_confident_false_positives(scanned) -> None:
    _, result = scanned("lookalikes")
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
    # Same local Supabase id but different linked projects: provably different databases.
    pairs = {frozenset((e.source, e.target)) for e in result.workspace.edges}
    assert frozenset(("linked-a", "linked-c")) not in pairs
    assert frozenset(("linked-b", "linked-c")) not in pairs


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


def test_mcp_tool_outputs_respect_budgets(scanned) -> None:
    from cairn.mcp_server import tools

    for name in REMOTES:
        ws, result = scanned(name)
        for repo in result.workspace.repos:
            assert estimate_tokens(tools.card_text(ws, repo.id)) <= result.config.card_budget
            related = tools.related_text(ws, repo.id, include_unconfirmed=True)
            assert len(related.splitlines()) <= tools.MAX_LINES + 2
        assert len(tools.find_across_text(ws, "a").splitlines()) <= tools.MAX_LINES + 1


def test_mcp_resolve_top_hit_equals_resolver(scanned) -> None:
    from cairn.mcp_server import tools

    ws, result = scanned("mini-eats")
    authored = load_authored(ws)
    for case in _expect("mini-eats")["phrasings"]:
        expected = resolve_repo(result.workspace, authored, case["query"])[0].repo_id
        assert tools.resolve_text(ws, case["query"]).startswith(f"- {expected} ")


def test_service_links_are_exact(scanned) -> None:
    """Spec §21.6: HTTP, gRPC, pub/sub, compose, env and monorepo links, with look-alikes
    (shared /health, an external API, a vague topic, a proto with no implementer) that must
    not link at all."""
    _, result = scanned("servicemesh")
    predicted = [
        (e.source, e.target, e.type.value, e.confidence.value) for e in result.workspace.edges
    ]
    expected = [
        (e["from"], e["to"], e["type"], e["confidence"]) for e in _expect("servicemesh")["edges"]
    ]
    metrics = edge_metrics(predicted, expected)
    assert metrics.recall >= 0.9, metrics.describe()
    assert metrics.precision == 1.0, metrics.describe()
    assert metrics.tier_accuracy == 1.0, metrics.describe()


def test_read_only_evals_share_one_scan_per_workspace(scanned) -> None:
    assert scanned("mini-eats") is scanned("mini-eats")


def test_real_world_service_links_are_exact(scanned) -> None:
    """Spec §24: Sock Shop's coupling styles (service DNS, host literals, Spring AMQP, deploy
    repos) with their look-alikes (localhost, a public API, a comment, mongo:3.4, catalogue-db,
    a repo that only declares a queue) that must not link."""
    _, result = scanned("microshop")
    predicted = {
        (e.source, e.target, e.type.value, e.confidence.value) for e in result.workspace.edges
    }
    expected = {
        (e["from"], e["to"], e["type"], e["confidence"]) for e in _expect("microshop")["edges"]
    }
    assert predicted == expected, (sorted(predicted - expected), sorted(expected - predicted))


def test_families_and_mongo_links_are_exact(scanned) -> None:
    """A registration site and its per-event clone are one family (and share no database link
    just for sharing a schema); an admin panel and a check-in app share MongoDB collections; a
    name-only copy is a suggestion; Firestore's look-alike collection calls link nothing."""
    _, result = scanned("eventsuite")
    predicted = {
        (*sorted((e.source, e.target)), e.type.value, e.confidence.value)
        for e in result.workspace.edges
    }
    expected = {
        (*sorted((e["from"], e["to"])), e["type"], e["confidence"])
        for e in _expect("eventsuite")["edges"]
    }
    assert predicted == expected, (sorted(predicted - expected), sorted(expected - predicted))
