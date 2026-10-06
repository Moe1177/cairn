"""Phase 4 Task 5: benchmark suites built from real repos pinned at exact commits."""

import subprocess
from pathlib import Path

import pytest
import yaml

from cairn.bench.sources import fetch_sources
from cairn.bench.suite import load_suite
from cairn.errors import CairnError


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


def _upstream(tmp_path: Path, name: str) -> tuple[str, str]:
    repo = tmp_path / "upstream" / name
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "index.ts").write_text("export const x = 1\n", encoding="utf-8")
    (repo / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 64)
    _git(repo.parent, "init", "-q", name)
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "-m", "x")
    return repo.as_uri(), _git(repo, "rev-parse", "HEAD")


def _suite(tmp_path: Path, sources: list[dict]) -> Path:
    suite_dir = tmp_path / "suite"
    suite_dir.mkdir()
    (suite_dir / "related.md").write_text("# related\n", encoding="utf-8")
    suite = {
        "name": "demo",
        "workspace": "fetched",
        "related_repos_doc": "related.md",
        "sources": sources,
        "tasks": [
            {"id": "t", "category": "control", "repo": "lib", "prompt": "p", "expect_files": []}
        ],
    }
    (suite_dir / "suite.yaml").write_text(yaml.safe_dump(suite), encoding="utf-8")
    return suite_dir


def test_sources_are_fetched_at_their_commit_without_binaries(tmp_path: Path) -> None:
    url, sha = _upstream(tmp_path, "lib")
    suite_dir = _suite(tmp_path, [{"name": "lib", "url": url, "sha": sha}])
    tree = fetch_sources(suite_dir, load_suite(suite_dir))
    lib = tree / "lib"
    assert (lib / "src" / "index.ts").is_file() and (lib / ".fixture-repo").is_file()
    assert not (lib / "logo.png").exists() and not (lib / ".git").exists()
    assert fetch_sources(suite_dir, load_suite(suite_dir)) == tree  # cached


def test_a_missing_commit_fails_clearly(tmp_path: Path) -> None:
    url, _ = _upstream(tmp_path, "lib")
    suite_dir = _suite(tmp_path, [{"name": "lib", "url": url, "sha": "0" * 40}])
    with pytest.raises(CairnError, match="lib"):
        fetch_sources(suite_dir, load_suite(suite_dir))


@pytest.mark.parametrize(
    "source",
    [
        {"name": "../escape", "url": "https://github.com/a/b.git", "sha": "a" * 40},
        {"name": "ok", "url": "https://github.com/a/b.git", "sha": "main"},
        {"name": "ok", "url": "ext::sh -c touch PWNED", "sha": "a" * 40},
    ],
)
def test_suite_sources_are_validated(tmp_path: Path, source: dict) -> None:
    suite_dir = _suite(tmp_path, [source])
    with pytest.raises(CairnError):
        load_suite(suite_dir)


def test_suites_without_sources_use_their_fixture_folder(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1] / "bench" / "suites" / "fleetline"
    assert fetch_sources(root, load_suite(root)) == root / "fixtures"


SUITES = Path(__file__).resolve().parents[1] / "bench" / "suites"


@pytest.mark.parametrize("name", ["sockshop", "supabase-js"])
def test_oss_suite_keys_exist_in_the_pinned_tree(name: str) -> None:
    suite_dir = SUITES / name
    suite = load_suite(suite_dir)
    assert suite.sources and len(suite.tasks) >= 6
    fetched = [p for p in (suite_dir / ".sources").glob("*") if (p / ".complete").is_file()]
    if not fetched:
        pytest.skip("sources not fetched (run the benchmark once, or fetch_sources)")
    tree = fetch_sources(suite_dir, suite)
    missing = [f for t in suite.tasks for f in t.expect_files if not (tree / f).is_file()]
    assert not missing
    repos = {t.repo for t in suite.tasks}
    assert repos <= {s.name for s in suite.sources}
