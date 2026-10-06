"""0.7 B1: three locators behind one interface — grep where grep wins, the graph where it wins."""

import json
import subprocess
from pathlib import Path

import pytest

from cairn.locate import grep as grep_module
from cairn.locate.grep import grep_locate
from cairn.locate.hybrid import hybrid_locate
from cairn.locate.terms import concept_terms, is_chain_question, literal_terms
from cairn.providers.graph import Graph, load_graph


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _repo(path: Path, files: dict[str, str], *, git: bool = True) -> Path:
    for rel, text in files.items():
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_text(text, encoding="utf-8")
    if git:
        _git(path, "init", "-q")
        _git(path, "add", "-A")
        _git(path, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "-m", "first")
    return path


SHOP = {
    "src/orders/service.py": (
        "from src.db import pool\n\n"
        "def getOrderById(order_id):\n"
        "    return pool.fetch(order_id)\n\n"
        "def cancel_order(order_id):\n"
        "    raise PaymentDeclined('card declined by issuer')\n"
    ),
    "src/api/routes.py": (
        "from src.orders.service import getOrderById\n\n"
        "@app.get('/api/orders/{id}')\n"
        "def read(id):\n"
        "    return getOrderById(id)\n"
    ),
    "tests/test_orders.py": "from src.orders.service import getOrderById\n\ngetOrderById(1)\n",
    "package-lock.json": '{"getOrderById": "noise"}\n',
    "web/app.min.js": "var getOrderById=function(){};" + "x" * 2000 + "\n",
    "src/billing/charge.py": "def charge(card):\n    return gateway.capture(card)\n",
}


# -- terms -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("where is getOrderById defined", ("getOrderById",)),
        ("what does cancel_order do", ("cancel_order",)),
        ("who publishes shipping-task", ("shipping-task",)),
        ("which handler serves GET /api/orders/{id}", ("/api/orders/",)),
        ('where is the error "card declined by issuer" raised', ("card declined by issuer",)),
        ("open service.py", ("service.py",)),
        ("where is OrderService", ("OrderService",)),
        ("read TRIPS_URL", ("TRIPS_URL",)),
    ],
)
def test_literal_terms_are_the_code_s_own_words(question: str, expected: tuple[str, ...]) -> None:
    assert literal_terms(question) == expected


@pytest.mark.parametrize(
    "question",
    ["where is the order logic", "how do users log in", "Where Is Payment Handled?"],
)
def test_plain_words_are_not_literal(question: str) -> None:
    assert literal_terms(question) == ()


def test_concept_terms_drop_question_words() -> None:
    assert concept_terms("where is the payment declined handled") == ("payment", "declined")


@pytest.mark.parametrize(
    ("question", "chain"),
    [
        ("who calls getOrderById", True),
        ("what breaks if I change cancel_order", True),
        ("where is getOrderById used", True),
        ("find usages of charge", True),
        ("where is getOrderById defined", False),
        ("how are orders cancelled", False),
    ],
)
def test_chain_questions(question: str, chain: bool) -> None:
    assert is_chain_question(question) is chain


# -- grep ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("git", [True, False], ids=["git", "no-git"])
def test_grep_puts_the_definition_first_and_skips_noise(tmp_path: Path, git: bool) -> None:
    repo = _repo(tmp_path / "shop", SHOP, git=git)
    result = grep_locate(repo, ("getOrderById",), limit=10)
    files = [h.file for h in result.hits]
    assert files[0] == "src/orders/service.py" and result.hits[0].line == 3
    assert files.index("src/api/routes.py") < files.index("tests/test_orders.py")
    assert "package-lock.json" not in files and "web/app.min.js" not in files
    assert all(h.source == "grep" for h in result.hits)


def test_grep_finds_a_quoted_message_and_regex_characters_are_literal(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "shop", SHOP)
    hit = grep_locate(repo, ("card declined by issuer",), limit=5).hits[0]
    assert (hit.file, hit.line) == ("src/orders/service.py", 7)
    assert grep_locate(repo, ("pool.fetch(",), limit=5).hits[0].file == "src/orders/service.py"
    assert grep_locate(repo, (".*",), limit=5).hits == ()


def test_grep_sees_files_not_yet_committed(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "shop", SHOP)
    (repo / "src" / "refunds.py").write_text("def issueRefund():\n    pass\n", encoding="utf-8")
    assert [h.file for h in grep_locate(repo, ("issueRefund",), limit=5).hits] == ["src/refunds.py"]


def test_grep_finds_a_file_by_name(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "shop", SHOP)
    assert grep_locate(repo, ("charge.py",), limit=5).hits[0].file == "src/billing/charge.py"


def test_grep_says_when_it_kept_only_the_best(tmp_path: Path) -> None:
    files = {f"src/m{i}.py": "import logging\n" for i in range(30)}
    repo = _repo(tmp_path / "big", files)
    result = grep_locate(repo, ("logging",), limit=5)
    assert len(result.hits) == 5 and result.files_matched == 30 and result.truncated


def test_grep_falls_back_when_git_cannot_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path / "shop", SHOP)
    monkeypatch.setattr(grep_module, "run_bytes", lambda *a, **k: None)
    assert grep_locate(repo, ("getOrderById",), limit=5).hits[0].file == "src/orders/service.py"


# -- hybrid --------------------------------------------------------------------------------------


def _graph(tmp_path: Path, symbols: list[tuple[str, str, int]]) -> Graph:
    nodes = [
        {"id": f"n{i}", "label": label, "source_file": file, "source_location": f"L{line}"}
        for i, (label, file, line) in enumerate(symbols)
    ]
    path = tmp_path / "graph.json"
    path.write_text(json.dumps({"nodes": nodes, "links": []}), encoding="utf-8")
    graph = load_graph(path)
    assert graph is not None
    return graph


SHOP_GRAPH = [
    ("getOrderById()", "src/orders/service.py", 3),
    ("cancel_order()", "src/orders/service.py", 6),
    ("charge()", "src/billing/charge.py", 1),
    ("read()", "src/api/routes.py", 4),
]


def test_a_literal_question_is_answered_by_grep(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "shop", SHOP)
    result = hybrid_locate(repo, "where is getOrderById defined", _graph(tmp_path, SHOP_GRAPH))
    assert result.route == "grep" and result.hits[0].file == "src/orders/service.py"


def test_grep_answers_first_and_the_graph_marks_agreement(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "shop", SHOP)
    result = hybrid_locate(repo, "where do we charge the card", _graph(tmp_path, SHOP_GRAPH))
    assert result.hits[0].file == "src/billing/charge.py"
    assert result.hits[0].source == "grep+graph" and result.hits[0].symbol == "charge()"


def test_the_graph_answers_when_grep_finds_nothing(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "shop", SHOP)
    result = hybrid_locate(repo, "where is cancelling handled", _graph(tmp_path, SHOP_GRAPH))
    assert result.route == "graph" and result.hits[0].symbol == "cancel_order()"


def test_the_graph_adds_no_places_when_grep_found_some(tmp_path: Path) -> None:
    """bench-locate: filling grep's empty slots with graph hits added no answers, only tokens."""
    repo = _repo(tmp_path / "shop", SHOP)
    graph = _graph(tmp_path, [*SHOP_GRAPH, ("orderCancelled()", "src/api/routes.py", 1)])
    assert hybrid_locate(repo, "anything cancelled", graph).route == "graph"  # grep finds nothing
    for question in ("where is getOrderById defined", "who calls cancel_order"):
        alone = hybrid_locate(repo, question, None, limit=10)
        both = hybrid_locate(repo, question, graph, limit=10)
        assert [h.file for h in both.hits] == [h.file for h in alone.hits]
        assert both.route == "grep"


def test_a_chain_question_puts_the_users_before_the_definition(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "shop", SHOP)
    result = hybrid_locate(repo, "who calls getOrderById", _graph(tmp_path, SHOP_GRAPH))
    files = [h.file for h in result.hits]
    assert files[0] == "src/api/routes.py" and "chain" in result.reason
    assert files.index("src/orders/service.py") > files.index("tests/test_orders.py")


def test_without_a_graph_plain_words_are_grepped(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "shop", SHOP)
    result = hybrid_locate(repo, "where is the payment declined", None)
    assert result.route == "grep" and result.hits[0].file == "src/orders/service.py"


def test_a_stale_graph_is_said_so(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "shop", SHOP)
    graph = _graph(tmp_path, SHOP_GRAPH)
    result = hybrid_locate(repo, "where is cancelling handled", graph, graph_stale=True)
    assert "stale" in result.reason


def test_every_hit_cites_a_line_that_exists(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "shop", SHOP)
    graph = _graph(tmp_path, [*SHOP_GRAPH, ("ghost()", "src/gone.py", 9)])
    for question in ("who calls getOrderById", "ghost", "cancel_order"):
        for hit in hybrid_locate(repo, question, graph).hits:
            lines = (repo / hit.file).read_text(encoding="utf-8").splitlines()
            assert hit.line is None or 1 <= hit.line <= len(lines)


@pytest.mark.parametrize("git", [True, False], ids=["git", "no-git"])
def test_grep_skips_binaries_and_generated_lines(tmp_path: Path, git: bool) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / "blob.bin").write_bytes(b"\x00\x01getOrderById\x00")
    _repo(
        repo,
        {
            "bundle.js": "var a=1;getOrderById();" + "y" * 1000 + "\n",
            "src/order.py": "def getOrderById():\n    pass\n",
        },
        git=git,
    )
    assert [h.file for h in grep_locate(repo, ("getOrderById",), limit=5).hits] == ["src/order.py"]


def test_a_term_that_looks_like_an_option_is_searched_for(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r", {"run.sh": "git push --force-with-lease\n"})
    assert grep_locate(repo, ("--force-with-lease",), limit=5).hits[0].file == "run.sh"


# -- final review fixes --------------------------------------------------------------------------

SECRET = "sk_live_abc123XYZ"
NEVER_OPEN = {
    ".env": f"STRIPE_SECRET_KEY={SECRET}\n",
    "config/.env.production": f"KEY={SECRET}\n",
    "deploy/secrets.yaml": f"stripe: {SECRET}\n",
    "infra/prod.tfvars": f'key = "{SECRET}"\n',
    "api/appsettings.Production.json": f'{{"Key": "{SECRET}"}}\n',
    "ops/db-secret.json": f'{{"k": "{SECRET}"}}\n',
    ".docker/config.json": f'{{"auth": "{SECRET}"}}\n',
}


@pytest.mark.parametrize("git", [True, False], ids=["git", "no-git"])
def test_never_open_files_are_never_searched(tmp_path: Path, git: bool) -> None:
    """Spec §20.1: cairn never opens secret files, so no answer can confirm a guessed value."""
    repo = _repo(tmp_path / "r", {**NEVER_OPEN, "src/pay.py": "KEY = load('stripe')\n"}, git=git)
    for guess in (SECRET, "sk_live_abc", "STRIPE_SECRET_KEY"):
        assert grep_locate(repo, (guess,), limit=10).hits == ()
        hits = hybrid_locate(repo, f'where is "{guess}" read?', None).hits
        assert {h.file for h in hits} <= {"src/pay.py"}  # never a secret file
    for name in (".env", "secrets.yaml", "prod.tfvars", "appsettings.Production.json"):
        assert grep_locate(repo, (name,), limit=10).hits == ()


def test_a_grep_hit_names_the_symbol_that_encloses_its_line(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "shop", SHOP)
    graph = _graph(tmp_path, SHOP_GRAPH)
    message = hybrid_locate(repo, '"card declined by issuer"', graph).hits[0]
    assert (message.line, message.symbol) == (7, "cancel_order()")  # line 7 is inside it
    definition = hybrid_locate(repo, "where is getOrderById defined", graph).hits[0]
    assert (definition.line, definition.symbol) == (3, "getOrderById()")


def test_a_stale_index_adds_no_symbols_to_grep_hits(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "shop", SHOP)
    graph = _graph(tmp_path, SHOP_GRAPH)
    result = hybrid_locate(repo, "where is getOrderById defined", graph, graph_stale=True)
    assert result.hits and all(h.symbol is None for h in result.hits)
    assert result.route == "grep"


def test_a_huge_result_is_capped_and_said_to_be_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path / "big", {f"src/m{i}.py": "import logging\n" * 20 for i in range(40)})
    monkeypatch.setattr(grep_module, "GREP_MAX_BYTES", 600)
    result = grep_locate(repo, ("logging",), limit=5)
    assert result.hits and result.partial


def test_a_git_timeout_is_partial_and_does_not_search_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cairn.discover.proc import Capped

    repo = _repo(tmp_path / "shop", SHOP)
    monkeypatch.setattr(
        grep_module, "run_bytes_capped", lambda *a, **k: Capped(None, b"", False, True)
    )
    monkeypatch.setattr(grep_module, "_python_grep", lambda *a: pytest.fail("searched twice"))
    assert grep_locate(repo, ("getOrderById",), limit=5, names=False).partial


def test_the_fallback_says_when_it_stopped_early(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path / "shop", SHOP, git=False)
    monkeypatch.setattr(grep_module, "_FALLBACK_FILES", 1)
    assert grep_locate(repo, ("getOrderById",), limit=5).partial


@pytest.mark.parametrize("term", ["real-time", "up-to-date", "end-to-end", "APIs", "IDs"])
def test_hyphenated_english_and_plural_acronyms_are_weak_literals(term: str) -> None:
    from cairn.locate.terms import is_weak

    assert is_weak(term)
    assert not is_weak("shipping_task") and not is_weak("getOrderById") and not is_weak("v2-api")


def test_a_weak_literal_does_not_hide_the_question_s_words(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path / "app",
        {
            "src/ui.py": "# real-time updates are shown here\nrender()\n",
            "docs/overview.md": "The real-time pipeline.\n",
            "src/order_sync.py": "def sync_orders(order):\n    return order\n",
        },
    )
    result = hybrid_locate(repo, "where is the real-time order sync handled?", None)
    assert "src/order_sync.py" in [h.file for h in result.hits[:3]]
