"""Phase 2e Tasks 11-12 (spec §20.4): CI, release, and community files a newcomer expects."""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _workflow(name: str) -> tuple[str, dict]:
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    return text, yaml.safe_load(text)


def test_ci_is_hardened_and_tests_the_built_wheel() -> None:
    text, ci = _workflow("ci.yml")
    assert ci["permissions"] == {"contents": "read"}
    assert "concurrency" in ci
    assert "--locked" in text
    full = _combos(ci["jobs"]["test"], pr=False)
    assert {os for os, _ in full} == {"ubuntu-latest", "windows-latest", "macos-latest"}
    assert {py for _, py in full} >= {"3.11", "3.12", "3.13", "3.14"} and len(full) == 12
    assert "lowest-direct" in text
    assert re.search(r"pip install .*dist/.*\.whl", text) and "cairn --version" in text
    assert "persist-credentials: false" in text
    for uses in re.findall(r"uses:\s*(\S+)", text):
        assert re.search(r"@[0-9a-f]{40}$", uses), f"unpinned action {uses}"


def test_release_uses_trusted_publishing() -> None:
    text, release = _workflow("release.yml")
    publish = release["jobs"]["publish"]
    assert publish["permissions"] == {"id-token": "write"}
    assert publish["environment"]["name"] == "pypi"
    assert "pypa/gh-action-pypi-publish@" in text
    assert "password" not in text and "PYPI_TOKEN" not in text
    for uses in re.findall(r"uses:\s*(\S+)", text):
        assert re.search(r"@[0-9a-f]{40}$", uses), f"unpinned action {uses}"


def test_dependabot_watches_actions_and_uv() -> None:
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    ecosystems = {u["package-ecosystem"] for u in config["updates"]}
    assert ecosystems == {"github-actions", "uv"}


@pytest.mark.parametrize(
    "name",
    [
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "CODE_OF_CONDUCT.md",
        ".github/PULL_REQUEST_TEMPLATE.md",
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/feature_request.yml",
        ".github/ISSUE_TEMPLATE/config.yml",
    ],
)
def test_community_files_exist(name: str) -> None:
    path = ROOT / name
    assert path.is_file() and len(path.read_text(encoding="utf-8").strip()) > 40
    if path.suffix == ".yml":
        yaml.safe_load(path.read_text(encoding="utf-8"))


def test_gitignore_covers_common_junk() -> None:
    lines = set((ROOT / ".gitignore").read_text(encoding="utf-8").splitlines())
    assert {".DS_Store", "*.egg-info/", "build/", ".idea/", ".env"} <= lines


DOCS = ["README.md", "CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md"]


def test_readme_documents_every_command() -> None:
    from typer.main import get_command

    from cairn.cli import app

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for name in get_command(app).commands:  # type: ignore[attr-defined]
        assert f"cairn {name}" in readme, name
    for heading in ("## Uninstall", "## Troubleshooting", "## Safety", "**Exit codes:**"):
        assert heading in readme
    assert "no network calls and collects no telemetry" in readme


def test_docs_have_no_private_names() -> None:
    # Names that must never be published live in a git-ignored local file (one per line), so
    # this test itself doesn't publish them. Without the file there is nothing to check.
    names_file = ROOT / ".superpowers" / "private-names.txt"
    if not names_file.is_file():
        pytest.skip("no local private-names list")
    names = [n.strip().lower() for n in names_file.read_text("utf-8").splitlines() if n.strip()]
    tracked = [ROOT / d for d in DOCS] + sorted((ROOT / "bench" / "published").glob("*.md"))
    tracked += sorted((ROOT / "tests").rglob("*.py")) + sorted((ROOT / "src").rglob("*.py"))
    for path in tracked:
        text = path.read_text(encoding="utf-8").lower()
        assert not any(name in text for name in names), path.name


def test_local_links_resolve() -> None:
    for name in DOCS:
        text = (ROOT / name).read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)\s]+)\)", text):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            assert (ROOT / target.split("#", 1)[0]).exists(), f"{name}: {target}"


def test_security_claims_match_the_code() -> None:
    # final review I10: names do appear in INDEX; git's hooks and filters are what's disabled.
    for name in ("SECURITY.md", "README.md", "CHANGELOG.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "filters" in text and "hooks" in text, name
        assert "folder names) is flattened and capped, and kept out" not in text, name


def test_graphify_is_an_optional_extra_tested_in_ci() -> None:
    import tomllib

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["optional-dependencies"]["graphify"] == ["graphifyy>=0.9.77,<0.10"]
    assert "graphifyy" not in " ".join(project["dependencies"])
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "--extra graphify" in ci


def test_readme_explains_deep_queries() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## Deep queries" in readme
    for needle in ("cairn deep build", "cairnmap[graphify]", "--code-only", "cairn refresh --deep"):
        assert needle in readme, needle


def _combos(job: dict, *, pr: bool) -> set[tuple[str, str]]:
    """The (os, python) jobs a matrix runs on a pull request or on main."""
    matrix = job["strategy"]["matrix"]
    flag = "yes" if pr else "no"
    excluded = [e for e in matrix.get("exclude", []) if e.get("pr", flag) == flag]
    return {
        (os_name, py)
        for os_name in matrix["os"]
        for py in matrix.get("python", ["-"])
        if not any(e.get("os", os_name) == os_name and e.get("python", py) == py for e in excluded)
    }


def test_pull_requests_run_a_smaller_matrix_on_every_os() -> None:
    text, ci = _workflow("ci.yml")
    assert "github.event_name == 'pull_request' && 'yes' || 'no'" in text
    small = _combos(ci["jobs"]["test"], pr=True)
    assert len(small) == 4
    assert {os for os, _ in small} == {"ubuntu-latest", "windows-latest", "macos-latest"}
    assert {py for _, py in small} == {"3.11", "3.12", "3.13", "3.14"}
    assert _combos(ci["jobs"]["package"], pr=True) == {("ubuntu-latest", "-")}
    assert len(_combos(ci["jobs"]["package"], pr=False)) == 3


def test_ci_runs_nightly_and_never_hangs() -> None:
    _, ci = _workflow("ci.yml")
    triggers = ci[True] if True in ci else ci["on"]  # YAML 1.1 reads `on:` as True
    assert triggers["schedule"] and "workflow_dispatch" in triggers
    for name, job in ci["jobs"].items():
        assert 0 < job["timeout-minutes"] <= 30, name
    assert (
        "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in _workflow("ci.yml")[0]
    )
    assert "-n auto" in _workflow("ci.yml")[0]
    assert "cache-dependency-glob" in _workflow("ci.yml")[0]


def test_jobs_no_runner_picked_up_are_retried_once_and_safely() -> None:
    text, rerun = _workflow("rerun.yml")
    triggers = rerun[True] if True in rerun else rerun["on"]
    assert triggers["workflow_run"]["workflows"] == ["ci"]
    assert rerun["permissions"] == {"actions": "write"}
    assert "actions/checkout" not in text and "run_attempt == 1" in text
    assert "${{ github.event" not in rerun["jobs"]["rerun"]["steps"][0]["run"]
    assert rerun["jobs"]["rerun"]["timeout-minutes"] <= 10
