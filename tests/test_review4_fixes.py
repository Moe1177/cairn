"""Phase 4 final-review fixes: fetched-source safety, resume integrity, statistics, detectors."""

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from cairn.bench.conditions import prepare
from cairn.bench.grading import Grade
from cairn.bench.report import render_markdown
from cairn.bench.run import RunRecord, run_bench
from cairn.bench.runner import FakeRunner, RunResult
from cairn.bench.stats import holm, wilcoxon
from cairn.bench.suite import load_suite
from cairn.errors import CairnError
from cairn.model.graph import EdgeType
from cairn.scan import scan_workspace
from tests.helpers import make_repo

SUITE = Path(__file__).resolve().parents[1] / "bench" / "suites" / "shopverse"


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


# -- Critical: a fetched source must never run code ------------------------------------------


def test_a_fetched_source_cannot_plant_git_hooks(tmp_path: Path) -> None:
    marker = tmp_path / "PWNED.txt"
    upstream = tmp_path / "upstream" / "lib"
    (upstream / "dot-git" / "hooks").mkdir(parents=True)
    (upstream / "dot-git" / "hooks" / "pre-commit").write_text(
        f"#!/bin/sh\necho x > '{marker.as_posix()}'\n", encoding="utf-8"
    )
    (upstream / "dot-env.example").write_text("API_URL=\n", encoding="utf-8")
    (upstream / "nested").mkdir()
    (upstream / "nested" / ".fixture-repo").write_text("", encoding="utf-8")
    (upstream / "index.ts").write_text("export const x = 1\n", encoding="utf-8")
    _git(upstream.parent, "init", "-q", "lib")
    _git(upstream, "add", "-A")
    _git(upstream, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "-m", "x")
    suite_dir = tmp_path / "suite"
    suite_dir.mkdir()
    (suite_dir / "related.md").write_text("# r\n", encoding="utf-8")
    sha = _git(upstream, "rev-parse", "HEAD")
    suite = {
        "name": "demo",
        "workspace": "fetched",
        "related_repos_doc": "related.md",
        "sources": [{"name": "lib", "url": upstream.as_uri(), "sha": sha}],
        "tasks": [{"id": "t", "category": "control", "repo": "lib", "prompt": "p"}],
    }
    (suite_dir / "suite.yaml").write_text(yaml.safe_dump(suite), encoding="utf-8")
    prepared = prepare("A", load_suite(suite_dir), suite_dir, tmp_path / "run")
    assert not marker.exists()
    lib = prepared.ws / "lib"
    assert (lib / "dot-env.example").is_file()  # upstream names are kept as they are
    assert not (lib / "nested" / ".git").exists()  # a nested marker makes no extra repo


@pytest.mark.parametrize("names", [["lib", "lib"], ["con"], ["NUL.txt"]])
def test_source_names_are_unique_and_portable(tmp_path: Path, names: list[str]) -> None:
    suite_dir = tmp_path / "suite"
    suite_dir.mkdir()
    sources = [{"name": n, "url": "https://github.com/a/b.git", "sha": "a" * 40} for n in names]
    suite = {
        "name": "demo",
        "workspace": "fetched",
        "related_repos_doc": "r.md",
        "sources": sources,
        "tasks": [],
    }
    (suite_dir / "suite.yaml").write_text(yaml.safe_dump(suite), encoding="utf-8")
    with pytest.raises(CairnError):
        load_suite(suite_dir)


# -- Resume integrity --------------------------------------------------------------------------

LIMIT = "You've hit your session limit"


def _reply_ok(prompt: str, cwd: Path) -> str:
    return json.dumps({"result": "x", "num_turns": 1, "total_cost_usd": 0.01, "usage": {}})


def _bench(tmp_path: Path, reply, model: str, **kwargs):  # type: ignore[no-untyped-def]
    return run_bench(
        SUITE,
        conditions=("A",),
        runs=2,
        task_ids=("cart-total",),
        runner=FakeRunner(reply),
        out_dir=tmp_path / "out",
        now="20261006-120000",
        meta={"model": model},
        **kwargs,
    )


def test_resume_refuses_a_different_model_or_settings(tmp_path: Path) -> None:
    _bench(tmp_path, _reply_ok, "sonnet")
    log = tmp_path / "out" / "20261006-120000.jsonl"
    with pytest.raises(CairnError, match="model"):
        _bench(tmp_path, _reply_ok, "haiku", resume=log)


def test_resume_reruns_only_usage_limit_failures(tmp_path: Path) -> None:
    log = tmp_path / "out" / "20261006-120000.jsonl"
    log.parent.mkdir(parents=True)
    rows = [
        {"_header": {"model": "sonnet", "suite": "shopverse", "runs": 2, "conditions": ["A"]}},
        {
            "condition": "A",
            "task_id": "cart-total",
            "run": 0,
            "grade": {"success": False, "recall": 0.0, "precision": 0.0},
            "result": {"result_text": "max turns reached", "is_error": True},
        },
        {
            "condition": "A",
            "task_id": "cart-total",
            "run": 1,
            "grade": {"success": False, "recall": 0.0, "precision": 0.0},
            "result": {"result_text": LIMIT, "is_error": True},
        },
    ]
    log.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    calls = []

    def reply(prompt: str, cwd: Path) -> str:
        calls.append(1)
        return _reply_ok(prompt, cwd)

    records = _bench(tmp_path, reply, "sonnet", resume=log)
    assert len(calls) == 1  # only run 1 (the limit); run 0's genuine error stands
    assert [r.result.is_error for r in sorted(records, key=lambda r: r.run)] == [True, False]


def test_a_stopped_run_leaves_a_log_to_resume(tmp_path: Path) -> None:
    def limited(prompt: str, cwd: Path) -> str:
        return json.dumps({"result": LIMIT, "is_error": True})

    with pytest.raises(CairnError, match="--resume"):
        _bench(tmp_path, limited, "sonnet")
    assert (tmp_path / "out" / "20261006-120000.jsonl").is_file()


# -- Statistics --------------------------------------------------------------------------------


def test_differences_of_thirds_tie_as_they_should() -> None:
    # 1 - 2/3, 1/3 - 2/3 and 2/3 - 1/3 are +-1/3 but differ in the last float bit.
    assert wilcoxon([1, 1 / 3, 2 / 3], [2 / 3, 2 / 3, 1 / 3]).p_value == pytest.approx(1.0)


def test_holm_adjusts_a_family_of_p_values() -> None:
    assert holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    assert holm([]) == []


def _paired_records() -> list[RunRecord]:
    out = []
    for task in range(6):
        for condition, ok, cost in (("A", False, 0.10), ("B", True, 0.05), ("C", True, 0.04)):
            out.append(
                RunRecord(
                    condition,
                    f"t{task}",
                    0,
                    Grade(ok, float(ok), float(ok)),
                    RunResult("r", cost_usd=cost),
                )
            )
    return out


def test_reports_adjust_p_values_and_say_so() -> None:
    md = render_markdown(_paired_records())
    assert "Holm" in md
    header = next(line for line in md.splitlines() if line.startswith("| Comparison |"))
    assert "p adj" in header


def test_break_even_states_what_it_leaves_out_and_its_evidence() -> None:
    md = render_markdown(_paired_records())
    assert "pays for itself" not in md
    assert "not counted" in md  # summary authoring, the doc's writing time
    row = next(line for line in md.splitlines() if line.startswith("| C break-even |"))
    assert "$0.0600" in row and "p = 0.031" in row
    assert next(line for line in md.splitlines() if line.startswith("| B break-even |"))


# -- Detector look-alikes ----------------------------------------------------------------------

LOOKALIKES = {
    "knexfile.js": 'module.exports = { connection: { host: "db", port: 5432 } };\n',
    "cache.js": 'const client = redis.createClient({ host: "cache" });\n',
    "client.ts": 'fetch(url, { headers: { Host: "api" } });\n',
    "site.yml": '- hosts: "web"\n  roles: [nginx]\n',
    "docker-compose.override.yml": 'services:\n  x:\n    hostname: "app"\n',
    "notes.js": "call(); // see http://catalogue/ for the API\n",
    "helpers.py": '"""Talks to the user service.\n\nSee http://user/ for details.\n"""\nX = 1\n',
    ".github/workflows/ci.yml": (
        "jobs:\n  b:\n    steps:\n      - uses: actions/checkout@v4\n"
        "        with:\n          repository: acme/storefront\n"
    ),
    "monitoring/grafana.yaml": "image: grafana/grafana:10.2.0\n",
}


def test_realistic_lookalikes_never_link(tmp_path: Path) -> None:
    for name in ("db", "cache", "api", "web", "app", "catalogue", "user", "grafana", "storefront"):
        make_repo(tmp_path, name, {"README.md": f"# {name}\n"})
    make_repo(tmp_path, "ops", LOOKALIKES)
    edges = scan_workspace(tmp_path).workspace.edges
    assert not [e for e in edges if e.source == "ops"], [
        (e.target, e.type.value) for e in edges if e.source == "ops"
    ]


def test_real_service_hosts_and_deploys_still_link(tmp_path: Path) -> None:
    for name in ("payment", "catalogue", "carts"):
        make_repo(tmp_path, name, {"README.md": f"# {name}\n"})
    make_repo(
        tmp_path,
        "orders",
        {"Config.java": 'return new ServiceUri(new Hostname("payment"), d, "/x").toUri();\n'},
    )
    make_repo(
        tmp_path,
        "deploy",
        {
            "compose.yml": "services:\n  a:\n    image: acme/catalogue:1\n  b:\n    image: acme/carts:2\n",
            "helm/values.yaml": "payment:\n  image:\n    repository: acme/payment\n    tag: 1\n",
        },
    )
    edges = {(e.source, e.target, e.type) for e in scan_workspace(tmp_path).workspace.edges}
    assert ("orders", "payment", EdgeType.CALLS_HTTP) in edges
    assert {("deploy", t, EdgeType.DEPLOYS) for t in ("catalogue", "carts", "payment")} <= edges


def test_amqp_exchange_names_are_not_queues(tmp_path: Path) -> None:
    make_repo(
        tmp_path,
        "billing",
        {"B.java": 'template.convertAndSend("orders.events", "order.paid", event);\n'},
    )
    make_repo(
        tmp_path,
        "mailer",
        {"M.java": '@RabbitListener(queues = "orders.events")\npublic void on(Event e) {}\n'},
    )
    edges = scan_workspace(tmp_path).workspace.edges
    assert not [e for e in edges if e.type is EdgeType.PUBSUB]
