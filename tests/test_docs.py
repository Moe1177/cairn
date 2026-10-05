from pathlib import Path

from cairn.detectors.docs import DocsDetector, alias_pattern
from tests.helpers import ctx_for, make_repo

TABLE = {"shopapp": "shopapp", "shop-admin": "shop-admin", "notes": "notes", "admin": "shop-admin"}


def _targets(result) -> list[str]:
    return [f.value for f in result.consumes]


def test_mentions_sibling_by_id(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "shopapp", {"CLAUDE.md": "# shopapp\n\nThe owner dashboard is the shop-admin repo.\n"})
    result = DocsDetector().run(ctx_for(tmp_path, repo, alias_table=TABLE))
    assert _targets(result) == ["shop-admin"]
    assert result.consumes[0].evidence[0].line == 3


def test_prefix_id_inside_longer_id_is_not_a_mention(tmp_path: Path) -> None:
    # Review Focus 2
    repo = make_repo(tmp_path, "shop-admin", {"README.md": "# shop-admin\n\nThe shop-admin dashboard.\n"})
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
