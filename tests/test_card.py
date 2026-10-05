import pytest

from cairn.model.graph import (
    Command,
    Confidence,
    Contracts,
    DetectorError,
    Edge,
    EdgeType,
    Evidence,
    Fact,
    FactKind,
    LayoutEntry,
    Repo,
    Workspace,
)
from cairn.model.overrides import Authored
from cairn.render.card import render_card
from cairn.render.tokens import estimate_tokens


def _admin(**overrides) -> Repo:
    base = dict(
        id="shop-admin",
        path="shop-admin",
        app_roots=("shop-admin/shop-admin",),
        stack=("typescript", "nextjs"),
        head_sha="a1b2c3d",
        commands=(Command(name="dev", run="cd shop-admin && npm run dev"),),
        layout=(
            LayoutEntry(path="shop-admin/app/", purpose="routes/pages"),
            LayoutEntry(path="shop-admin/zz/"),
        ),
        readme_excerpt="Owner portal.",
        contracts=Contracts(exposes=(Fact(kind=FactKind.DB_TABLE, value="platform_discounts"),)),
    )
    return Repo(**{**base, **overrides})


def _ws(repo: Repo, edges=()) -> Workspace:
    return Workspace(
        workspace_root="/ws",
        generated_at="t",
        repos=(repo, Repo(id="shopapp", path="shopapp")),
        edges=tuple(edges),
    )


EDGE = Edge(
    source="shop-admin",
    target="shopapp",
    type=EdgeType.SHARES_DB,
    confidence=Confidence.EXTRACTED,
    score=0.84,
    signals=("db_table:cook_profiles", "db_table:listings"),
    evidence=(
        Evidence(repo="shop-admin", file="lib/q.ts", line=12, snippet="FROM cook_profiles"),
    ),
    why="Admin reads the same tables.",
)


def test_header_and_sections() -> None:
    card = render_card(
        _admin(),
        _ws(_admin(), [EDGE]),
        authored=Authored(summary="Restaurant-owner dashboard."),
        note="Never write orders directly.",
    )
    lines = card.splitlines()
    assert lines[0] == "# shop-admin"
    assert lines[1] == "> Restaurant-owner dashboard."
    assert lines[2] == "`./shop-admin` · typescript, nextjs · HEAD a1b2c3d"
    assert lines[3] == "app: `./shop-admin/shop-admin`"
    assert (
        '→ shopapp: shares tables cook_profiles, listings — "Admin reads the same tables." (extracted · lib/q.ts:12)'
        in card
    )
    assert "dev `cd shop-admin && npm run dev`" in card
    assert "shop-admin/app/ → routes/pages" in card and "\nshop-admin/zz/\n" in card
    assert "db table platform_discounts" in card
    assert (
        card.index("## Relates")
        < card.index("## Run")
        < card.index("## Layout")
        < card.index("## Exposes")
        < card.index("## Notes")
    )


def test_readme_fallback_and_missing_summary() -> None:
    assert "> Owner portal. (auto from README)" in render_card(_admin(), _ws(_admin()))
    bare = _admin(readme_excerpt=None)
    assert "> (no summary yet)" in render_card(bare, _ws(bare))


def test_incoming_edge_arrow_and_foreign_evidence() -> None:
    edge = Edge(
        source="shopapp",
        target="shop-admin",
        type=EdgeType.MENTIONS,
        confidence=Confidence.INFERRED,
        score=0.5,
        signals=("doc_mention",),
        evidence=(Evidence(repo="shopapp", file="CLAUDE.md", line=3, snippet="x"),),
    )
    card = render_card(_admin(), _ws(_admin(), [edge]))
    assert "← shopapp: docs mention (inferred · shopapp/CLAUDE.md:3)" in card


def test_warnings_and_dirty_marker() -> None:
    repo = _admin(
        dirty=True, detector_errors=(DetectorError(detector="database", message="ValueError: bad"),)
    )
    card = render_card(repo, _ws(repo))
    assert "HEAD a1b2c3d (uncommitted changes)" in card
    assert "⚠ database detector failed: ValueError: bad" in card


def test_budget_truncates_long_sections() -> None:
    tables = tuple(Fact(kind=FactKind.DB_TABLE, value=f"table_number_{i}") for i in range(300))
    repo = _admin(contracts=Contracts(exposes=tables))
    card = render_card(repo, _ws(repo), budget=400)
    assert estimate_tokens(card) <= 400
    assert "more)" in card


def test_estimate_is_close_to_a_real_tokenizer() -> None:
    tiktoken = pytest.importorskip("tiktoken")
    try:
        encoding = tiktoken.get_encoding("cl100k_base")
    except Exception:
        pytest.skip("tokenizer data unavailable offline")
    card = render_card(
        _admin(), _ws(_admin(), [EDGE]), authored=Authored(summary="Restaurant-owner dashboard.")
    )
    real = len(encoding.encode(card))
    assert abs(estimate_tokens(card) - real) / real <= 0.35
