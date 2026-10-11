"""Hard tasks: no search for the prompt's own words leads to the answer (`cairn bench-reach`)."""

from pathlib import Path

import yaml
from typer.testing import CliRunner

from cairn.bench.reach import Corpus, load_corpus, prompt_terms, reach, summarize
from cairn.bench.suite import Task
from cairn.cli import app
from tests.helpers import make_repo


def _task(prompt: str, files: tuple[str, ...], *, repo: str = "web", hard: bool = True) -> Task:
    return Task(id="t", category="impact", repo=repo, prompt=prompt, expect_files=files, hard=hard)


def _corpus(files: dict[str, str]) -> Corpus:
    repos = tuple(sorted({f.split("/", 1)[0] for f in files}))
    return Corpus({k.lower(): v.lower() for k, v in files.items()}, repos)


def test_terms_are_words_quotes_parts_and_joined_neighbours() -> None:
    terms = prompt_terms('Rename the "scale.min" label on /system/{name} for the queue worker.')
    assert {"scale.min", "scale", "/system/{name}", "system", "label"} <= set(terms)
    assert {"queue worker", "queue-worker", "queue_worker", "queueworker"} <= set(terms)
    assert "on" not in terms  # too short to search for
    possessive = prompt_terms("The user's token and the API's key")
    assert "s token and the API" not in possessive and "token" in possessive
    assert "user-s" not in possessive  # a possessive's "s" joins nothing
    assert "x-id" in prompt_terms("set the 'x-id' header")


def test_a_search_for_the_prompts_own_words_answers_an_easy_task() -> None:
    corpus = _corpus(
        {
            "api/routes.go": 'r.Handle("/system/scale-function")',
            "cli/proxy.go": 'const path = "/system/scale-function"',
            "web/main.go": "package main",
        }
    )
    result = reach(
        _task("Who hard-codes scale-function?", ("api/routes.go", "cli/proxy.go")), corpus
    )
    assert result.reachable and result.problem
    assert (result.best_term, result.best_hits, result.best_files) == ("scale-function", 2, 2)


def test_an_answer_behind_an_identifier_found_in_code_needs_a_hop() -> None:
    corpus = _corpus(
        {
            "web/deploy.yaml": "image: ghcr.io/acme/edge:1.2",
            "edge/Makefile": "docker build -t ghcr.io/acme/edge .",
            "edge/server.go": "func routes() {}",
        }
    )
    prompt = "Which project produces the container this install runs as its proxy?"
    result = reach(_task(prompt, ("web/deploy.yaml", "edge/Makefile")), corpus)
    assert not result.reachable and not result.named and not result.problem
    assert result.coverage == 0.0


def test_a_search_that_matches_too_many_files_leads_nowhere() -> None:
    files = {f"web/f{i}.go": "gateway" for i in range(60)}
    files["api/gateway.go"] = "gateway"
    corpus = _corpus(files)
    result = reach(_task("Where is the gateway?", ("api/gateway.go",)), corpus)
    assert not result.reachable


def test_a_prompt_naming_the_answers_repo_gives_it_away() -> None:
    corpus = _corpus(
        {
            "nats-queue-worker/main.go": "x",
            "web/main.go": "y",
            "faas/a.go": "z",
        }
    )
    result = reach(
        _task("What does the queue worker read?", ("nats-queue-worker/main.go",)), corpus
    )
    assert result.named == ("nats-queue-worker",) and result.problem
    # The repo the agent starts in is no giveaway: it's already there.
    start = reach(
        _task(
            "What does the queue worker read?",
            ("nats-queue-worker/main.go",),
            repo="nats-queue-worker",
        ),
        corpus,
    )
    assert start.named == ()


def test_a_word_in_many_repo_names_names_none_of_them() -> None:
    corpus = _corpus({f"ipv-cri-{n}/a.yaml": "x" for n in ("address", "kbv", "dl")})
    result = reach(_task("Which ipv-cri stack?", ("ipv-cri-kbv/a.yaml",)), corpus)
    assert result.named == ()


def test_an_answer_file_that_isnt_there_is_a_broken_key() -> None:
    result = reach(_task("Where?", ("api/gone.go",), hard=False), _corpus({"api/a.go": "x"}))
    assert result.missing == ("api/gone.go",) and result.problem
    assert "no such file" in summarize("s", [result])


def test_keyword_only_tasks_cannot_be_marked_hard() -> None:
    task = Task(id="k", category="orientation", repo="web", prompt="Who?", hard=True)
    result = reach(task, _corpus({"web/a.go": "x"}))
    assert not result.checked and result.problem
    assert "not checked" in summarize("s", [result])


def test_the_corpus_skips_vendored_copies_but_not_test_data(tmp_path: Path) -> None:
    make_repo(
        tmp_path,
        "api",
        {
            "main.go": "package main",
            "vendor/lib/x.go": "vendored",
            "testdata/case.yaml": "fixture",
        },
    )
    corpus = load_corpus(tmp_path)
    assert {"api/main.go", "api/testdata/case.yaml"} <= corpus.texts.keys()
    assert "api/vendor/lib/x.go" not in corpus.texts and corpus.repos == ("api",)


def test_bench_reach_fails_on_a_hard_task_a_search_answers(tmp_path: Path) -> None:
    suite = tmp_path / "suite"
    fixture = suite / "fixture"
    make_repo(fixture, "web", {"app.js": "fetch(PAYMENTS_URL)"})
    make_repo(fixture, "pay", {"server.js": "router.post('/charge')"})
    tasks = [
        {
            "id": "easy",
            "category": "impact",
            "repo": "web",
            "prompt": "Who serves /charge?",
            "expect_files": ["pay/server.js"],
            "hard": True,
        }
    ]
    data = {"name": "s", "workspace": "fixture", "related_repos_doc": "r.md", "tasks": tasks}
    (suite / "suite.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    result = CliRunner().invoke(app, ["bench-reach", str(suite), "--cache", str(tmp_path / "c")])
    assert result.exit_code == 1 and "a search answers it (marked hard!)" in result.output
    tasks[0]["prompt"] = "Which service takes this app's card payments?"
    (suite / "suite.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    result = CliRunner().invoke(app, ["bench-reach", str(suite), "--cache", str(tmp_path / "c")])
    assert result.exit_code == 0, result.output
    assert "needs a hop" in result.output
