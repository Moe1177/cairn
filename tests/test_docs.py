from pathlib import Path

from cairn.detectors.docs import DocsDetector, alias_pattern
from tests.helpers import ctx_for, make_repo

TABLE = {"shopapp": "shopapp", "shop-admin": "shop-admin", "notes": "notes", "admin": "shop-admin"}


def _targets(result) -> list[str]:
    return [f.value for f in result.consumes]


def test_mentions_sibling_by_id(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path,
        "shopapp",
        {"CLAUDE.md": "# shopapp\n\nThe owner dashboard is the shop-admin repo.\n"},
    )
    result = DocsDetector().run(ctx_for(tmp_path, repo, alias_table=TABLE))
    assert _targets(result) == ["shop-admin"]
    assert result.consumes[0].evidence[0].line == 3


def test_prefix_id_inside_longer_id_is_not_a_mention(tmp_path: Path) -> None:
    # Review Focus 2
    repo = make_repo(
        tmp_path, "shop-admin", {"README.md": "# shop-admin\n\nThe shop-admin dashboard.\n"}
    )
    assert _targets(DocsDetector().run(ctx_for(tmp_path, repo, alias_table=TABLE))) == []


def test_plain_word_alias_needs_context(tmp_path: Path) -> None:
    prose = make_repo(tmp_path, "a", {"README.md": "Customers take notes on orders.\n"})
    coded = make_repo(tmp_path, "b", {"README.md": "Study material lives in `notes`.\n"})
    context = make_repo(tmp_path, "c", {"AGENTS.md": "See the notes repo for scripts.\n"})
    ctx = lambda repo: ctx_for(tmp_path, repo, alias_table=TABLE)  # noqa: E731
    assert _targets(DocsDetector().run(ctx(prose))) == []
    assert _targets(DocsDetector().run(ctx(coded))) == ["notes"]
    assert _targets(DocsDetector().run(ctx(context))) == ["notes"]


def test_nested_docs_are_ignored(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "x", {"docs/plan.md": "shop-admin everywhere\n"})
    assert _targets(DocsDetector().run(ctx_for(tmp_path, repo, alias_table=TABLE))) == []


def test_alias_pattern_is_case_insensitive() -> None:
    assert alias_pattern("shop-admin").search("Talk to SHOP-ADMIN team")
    assert not alias_pattern("shopapp").search("shop-admin")


TOOLS = {"faas-cli": "faas-cli", "store": "store", "orders-svc": "orders-svc"}


def _kinds(result) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for fact in result.consumes:
        found.setdefault(fact.kind.value, []).append(fact.value)
    return found


def test_running_a_sibling_as_a_command_is_using_a_tool(tmp_path: Path) -> None:
    readme = "\n".join(
        [
            "# cron-connector",
            "Log in first: `faas-cli login --password-stdin`.",
            "```bash",
            "echo -n $PASSWORD | faas-cli login --username admin",
            "OPENFAAS_URL=http://127.0.0.1 faas-cli store deploy nodeinfo",
            "faas-cli deploy",
            "```",
            "$ faas-cli list",
        ]
    )
    repo = make_repo(tmp_path, "cron-connector", {"README.md": readme})
    result = DocsDetector().run(ctx_for(tmp_path, repo, alias_table=TOOLS))
    assert _kinds(result) == {"doc_command": ["faas-cli"]}
    assert [ev.line for ev in result.consumes[0].evidence] == [2, 4, 5]  # evidence is capped


def test_a_sentence_starting_with_a_repo_name_is_a_mention(tmp_path: Path) -> None:
    readme = (
        "# shop\n\norders-svc handles refunds for this app.\n"
        "Install the [faas-cli](https://github.com/openfaas/faas-cli) and read `faas-cli`.\n"
        "```yaml\nimage: faas-cli/thing.json\n```\n"
    )
    repo = make_repo(tmp_path, "shop", {"README.md": readme})
    result = DocsDetector().run(ctx_for(tmp_path, repo, alias_table=TOOLS))
    assert _kinds(result) == {"doc_mention": ["faas-cli", "orders-svc"]}


def test_a_mention_of_a_tool_is_a_suggestion_unless_the_tool_names_the_repo_back() -> None:
    from cairn.match.matcher import RepoFacts, match_edges
    from cairn.model.graph import Contracts, Fact, FactKind

    def repo(id_: str, mentions=(), commands=()) -> RepoFacts:
        facts = tuple(Fact(kind=FactKind.DOC_MENTION, value=v) for v in mentions)
        facts += tuple(Fact(kind=FactKind.DOC_COMMAND, value=v) for v in commands)
        return RepoFacts(id=id_, path=id_, contracts=Contracts(consumes=facts))

    edges = match_edges(
        [
            repo("templates", mentions=["faas-cli"]),  # "see the faas-cli": how-to
            repo("connector", commands=["faas-cli"]),  # runs it: no link, but it's a tool
            repo("gateway", mentions=["faas-cli"]),
            repo("faas-cli", mentions=["gateway"]),  # the tool names the gateway back
            repo("orders", mentions=["payments"]),  # not a tool: a mention as before
            repo("payments"),
        ]
    )
    found = {(e.source, e.target, e.confidence.value) for e in edges}
    assert found == {
        ("templates", "faas-cli", "ambiguous"),
        ("gateway", "faas-cli", "inferred"),
        ("faas-cli", "gateway", "inferred"),
        ("orders", "payments", "inferred"),
    }
