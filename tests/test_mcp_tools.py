import subprocess
from pathlib import Path

import pytest

from cairn.mcp_server import tools
from cairn.render.tokens import estimate_tokens


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@e.com",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def ws(materialize) -> Path:
    root = materialize("mini-eats").resolve()
    tools.rescan(root)
    return root


def test_resolve_and_unknown(ws: Path) -> None:
    assert tools.resolve_text(ws, "admin dashboard").startswith("- eats-admin")
    assert "No repo matches" in tools.resolve_text(ws, "zzzz qqqq")


def test_card_and_suggestions(ws: Path) -> None:
    assert tools.card_text(ws, "admin").startswith("# eats-admin")  # alias resolves
    assert "Did you mean" in tools.card_text(ws, "eats-admn")


def test_related_hides_unconfirmed_by_default(ws: Path) -> None:
    text = tools.related_text(ws, "eats-admin")
    assert "→ eats: shares tables" in text and "→ shared-ui" in text
    assert "shares tables" not in tools.related_text(ws, "eats-admin", edge_type="mentions")


def test_find_across_lists_owners_and_users(ws: Path) -> None:
    text = tools.find_across_text(ws, "cook_profiles")
    assert "- eats exposes db table 'cook_profiles'" in text
    assert "- eats-admin consumes db table 'cook_profiles'" in text


def test_stale_repo_is_rescanned_before_answering(ws: Path) -> None:
    # Review Focus 3
    repo = ws / "eats-admin"
    (repo / "eats-admin" / "lib" / "extra.ts").write_text(
        "sql`SELECT * FROM listings`\n", encoding="utf-8"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "more")
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    assert f"HEAD {head}" in tools.card_text(ws, "eats-admin")


def test_outputs_are_capped(ws: Path) -> None:
    for text in (
        tools.find_across_text(ws, "e"),
        tools.related_text(ws, "eats"),
        tools.resolve_text(ws, "eats"),
    ):
        listed = [line for line in text.splitlines() if line.startswith(("-", "→", "←"))]
        assert len(listed) <= tools.MAX_LINES
    assert estimate_tokens(tools.card_text(ws, "eats")) <= 800


def test_cap_adds_a_more_line() -> None:
    capped = tools._cap([f"- {i}" for i in range(40)])
    assert len(capped) == tools.MAX_LINES + 1 and capped[-1] == "…(+10 more)"


def test_refresh_and_query(ws: Path) -> None:
    assert tools.refresh_text(ws).startswith("Refreshed 4 repos")
    answer = tools.query_text(ws, "eats", "where are orders created?")
    assert answer.startswith("eats: answered by grep") and "my-app/db/" in answer
