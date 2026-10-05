from pathlib import Path

from cairn.config import CairnConfig
from cairn.scan import scan_workspace
from cairn.scan_cache import cache_key, worktree_fingerprint


def _tables(result, repo_id: str) -> set[str]:
    repo = result.workspace.repo(repo_id)
    return {f.value for f in repo.contracts.consumes if f.kind.value == "db_table"}


def test_second_scan_comes_from_cache(materialize) -> None:
    ws = materialize("mini-eats").resolve()
    first = scan_workspace(ws)
    assert first.cached == ()
    second = scan_workspace(ws)
    assert set(second.cached) == {r.id for r in second.workspace.repos}
    assert second.workspace.edges == first.workspace.edges


def test_uncommitted_and_untracked_changes_invalidate(materialize) -> None:
    # Review Focus 1
    ws = materialize("mini-eats").resolve()
    scan_workspace(ws)
    lib = ws / "eats-admin" / "eats-admin" / "lib"
    (lib / "admin-queries.ts").write_text("sql`SELECT * FROM refunds_audit`\n", encoding="utf-8")
    third = scan_workspace(ws)
    assert "eats-admin" not in third.cached and "refunds_audit" in _tables(third, "eats-admin")
    (lib / "new-file.ts").write_text("sql`SELECT * FROM coupons_ledger`\n", encoding="utf-8")
    fourth = scan_workspace(ws)
    assert "coupons_ledger" in _tables(fourth, "eats-admin")
    assert set(fourth.cached) == {"eats", "notes", "shared-ui"}


def test_full_scan_ignores_cache(materialize) -> None:
    ws = materialize("mini-eats").resolve()
    scan_workspace(ws)
    assert scan_workspace(ws, use_cache=False).cached == ()


def test_key_depends_on_config_and_requires_git(tmp_path: Path) -> None:
    # Review Focus 2
    a = cache_key("abc1234", "fp", CairnConfig())
    assert a and a != cache_key("abc1234", "fp", CairnConfig(card_budget=600))
    assert cache_key(None, "fp", CairnConfig()) is None
    assert cache_key("abc", None, CairnConfig()) is None
    assert worktree_fingerprint(tmp_path) is None  # not a git repo


def test_corrupt_or_foreign_cache_is_ignored(materialize) -> None:
    ws = materialize("mini-eats").resolve()
    scan_workspace(ws)
    for entry in (ws / ".cairn" / "cache" / "repos").glob("*.json"):
        entry.write_text("{not json", encoding="utf-8")
    assert scan_workspace(ws).cached == ()
