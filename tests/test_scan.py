from datetime import UTC, datetime
from pathlib import Path

import pytest

import cairn.scan as scan_module
from cairn.detectors.base import DetectorContext, DetectorResult
from cairn.errors import CairnError
from cairn.model.graph import EdgeType
from cairn.scan import build_alias_table, scan_workspace
from tests.helpers import make_repo, write

NOW = datetime(2026, 10, 5, tzinfo=UTC)


def _workspace(tmp_path: Path) -> Path:
    make_repo(
        tmp_path,
        "eats",
        {
            "package.json": '{"name": "eats-web"}',
            "db/migrations/0.sql": "CREATE TABLE cook_profiles (id int);\nCREATE TABLE listings (id int);\n",
            "CLAUDE.md": "Owner tools live in the eats-admin repo.\n",
        },
    )
    make_repo(
        tmp_path,
        "eats-admin",
        {
            "package.json": '{"name": "eats-admin"}',
            "lib/q.ts": "sql`SELECT * FROM cook_profiles JOIN listings ON true`\n",
        },
    )
    return tmp_path


def test_scan_builds_repos_and_edges(tmp_path: Path) -> None:
    result = scan_workspace(_workspace(tmp_path), now=NOW)
    ws = result.workspace
    assert [r.id for r in ws.repos] == ["eats", "eats-admin"]
    assert ws.generated_at == "2026-10-05T00:00:00+00:00"
    assert ws.workspace_root == tmp_path.resolve().as_posix()
    edges = {(e.source, e.target, e.type) for e in ws.edges}
    assert ("eats-admin", "eats", EdgeType.SHARES_DB) in edges
    assert ("eats", "eats-admin", EdgeType.MENTIONS) in edges
    assert ws.repo("eats").aliases == ("eats", "eats-web")


def test_detector_crash_is_recorded_not_fatal(tmp_path: Path, monkeypatch) -> None:
    class Boom:
        id = "boom"

        def run(self, ctx: DetectorContext) -> DetectorResult:
            raise RuntimeError("kaboom ghp_FAKEfakeFAKEfakeFAKEfake1234567890")

    monkeypatch.setattr(
        scan_module, "RELATION_DETECTORS", (Boom(), *scan_module.RELATION_DETECTORS)
    )
    ws = scan_workspace(_workspace(tmp_path), now=NOW).workspace
    errors = ws.repo("eats").detector_errors
    assert errors[0].detector == "boom"
    assert "kaboom" in errors[0].message and "ghp_" not in errors[0].message
    assert ws.edges


def test_ignore_repos_and_relations_warnings(tmp_path: Path) -> None:
    _workspace(tmp_path)
    write(tmp_path, ".cairn/relations.yaml", "ignore_repos: [eats-admin]\nnotes:\n  ghost: x\n")
    result = scan_workspace(tmp_path, now=NOW)
    assert [r.id for r in result.workspace.repos] == ["eats"]
    assert any("ghost" in w for w in result.warnings)


def test_user_aliases_bypass_generic_filter(tmp_path: Path) -> None:
    _workspace(tmp_path)
    write(tmp_path, ".cairn/authored/eats-admin.yaml", "aliases: [api, owner portal]\n")
    ws = scan_workspace(tmp_path, now=NOW).workspace
    assert ws.repo("eats-admin").aliases == ("eats-admin", "api", "owner portal")


def test_alias_table_drops_collisions_and_ids_win() -> None:
    table = build_alias_table({"a": ["a", "shared", "b"], "b": ["b", "shared", "only-b"]})
    assert table == {"a": "a", "b": "b", "only-b": "b"}


def test_not_a_directory(tmp_path: Path) -> None:
    with pytest.raises(CairnError):
        scan_workspace(tmp_path / "missing")


def test_scanning_inside_a_git_repo_is_refused(tmp_path: Path) -> None:
    # Final review I7: `cairn init` inside a repo wrote into that repo.
    repo = make_repo(tmp_path, "single")
    (repo / "src").mkdir()
    for root in (repo, repo / "src"):
        with pytest.raises(CairnError) as info:
            scan_workspace(root)
        assert "folder that contains your repos" in str(info.value)
    assert not (repo / ".cairn").exists()
