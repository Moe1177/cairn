"""Final-review fixes: cache freshness and safe git calls (Phase 2c)."""

import os
import shutil
from pathlib import Path

import pytest

import cairn.detectors as detector_registry
from cairn.bench.workspace import materialize as materialize_tree
from cairn.detectors.base import Detector, DetectorContext, DetectorResult
from cairn.discover.git import git_info, summary_is_stale
from cairn.model.graph import EdgeType
from cairn.paths import repo_cache_dir
from cairn.scan import scan_workspace
from cairn.scan_cache import worktree_fingerprint


def _workspace(tmp_path: Path, repos: dict[str, dict[str, str]]) -> Path:
    src = tmp_path / "src"
    for name, files in repos.items():
        (src / name).mkdir(parents=True)
        (src / name / ".fixture-repo").write_text("", encoding="utf-8")
        for rel, text in files.items():
            path = src / name / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    return materialize_tree(src, tmp_path / "ws").resolve()


def _db_tables(result, repo_id: str) -> set[str]:
    contracts = result.workspace.repo(repo_id).contracts
    facts = (*contracts.exposes, *contracts.consumes)
    return {f.value for f in facts if f.kind.value == "db_table"}


def test_sibling_cloned_after_first_scan_links_on_refresh(tmp_path: Path) -> None:
    # Final review C1: path refs depend on which sibling repos exist.
    ws = _workspace(
        tmp_path,
        {
            "app": {"docker-compose.yml": "services:\n  lib:\n    build: ../lib\n"},
            "other": {"README.md": "# other\n"},
        },
    )
    first = scan_workspace(ws)
    assert not any(e.type is EdgeType.PATH_REF for e in first.workspace.edges)
    shutil.copytree(ws / "other", ws / "lib")  # a new repo appears next to app
    second = scan_workspace(ws)
    links = {(e.source, e.target) for e in second.workspace.edges if e.type is EdgeType.PATH_REF}
    assert ("app", "lib") in links


def test_non_ascii_untracked_file_edit_is_noticed(tmp_path: Path) -> None:
    # Final review I1: git C-quotes non-ASCII paths in porcelain output.
    ws = _workspace(tmp_path, {"app": {"README.md": "# app\n"}})
    schema = ws / "app" / "café" / "schema.sql"
    schema.parent.mkdir()
    schema.write_text("CREATE TABLE menus (id int);\n", encoding="utf-8")
    assert "menus" in _db_tables(scan_workspace(ws), "app")
    schema.write_text("CREATE TABLE loyalty_points (id int, pts int);\n", encoding="utf-8")
    again = scan_workspace(ws)
    assert "app" not in again.cached and "loyalty_points" in _db_tables(again, "app")


def test_fingerprint_survives_unquoted_utf8_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Final review I1: core.quotePath=false makes git print raw UTF-8 bytes.
    ws = _workspace(tmp_path, {"app": {"README.md": "# app\n"}})
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.quotePath")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "false")
    odd = ws / "app" / "Á-ø.txt"
    odd.write_text("one", encoding="utf-8")
    before = worktree_fingerprint(ws / "app")
    odd.write_text("two two", encoding="utf-8")
    after = worktree_fingerprint(ws / "app")
    assert before is not None and after is not None and before != after


def test_git_calls_ignore_hook_env_and_take_no_optional_locks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Final review I7: hooks export GIT_DIR/GIT_INDEX_FILE; refresh must not inherit them.
    ws = _workspace(tmp_path, {"app": {"a.txt": "a"}, "lib": {"b.txt": "b"}})
    expected = git_info(ws / "lib").head_sha
    monkeypatch.setenv("GIT_DIR", str(ws / "app" / ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(ws / "app" / ".git" / "index"))
    from cairn.discover.git import git_env

    env = git_env()
    assert env["GIT_OPTIONAL_LOCKS"] == "0"
    assert "GIT_DIR" not in env and "GIT_INDEX_FILE" not in env
    assert git_info(ws / "lib").head_sha == expected
    assert os.environ["GIT_DIR"]  # the caller's environment is left alone


def test_summary_sha_cannot_inject_git_options(tmp_path: Path) -> None:
    # Final review I8
    ws = _workspace(tmp_path, {"app": {"a.txt": "a"}})
    target = tmp_path / "pwned.txt"
    assert summary_is_stale(ws / "app", f"--output={target}", 50) is True
    assert not target.exists()


class _Flaky:
    id = "flaky"

    def run(self, ctx: DetectorContext) -> DetectorResult:
        raise OSError("file locked by another process")


def test_repos_with_detector_errors_are_not_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Final review M4 (re-graded): a transient failure must not be pinned in the cache.
    ws = _workspace(tmp_path, {"app": {"a.txt": "a"}})
    registry: tuple[Detector, ...] = (*detector_registry.RELATION_DETECTORS, _Flaky())
    monkeypatch.setattr(detector_registry, "RELATION_DETECTORS", registry)
    scan_workspace(ws)
    assert not (repo_cache_dir(ws) / "app.json").exists()
