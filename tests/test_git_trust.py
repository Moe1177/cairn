"""0.6 Task 3: say so when git refuses a repo (dubious ownership) instead of degrading quietly."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

import cairn.doctor as doctor
import cairn.scan as scan_module
from cairn.cli import app
from cairn.discover import git as git_module
from cairn.discover.git import GitInfo
from cairn.discover.proc import Completed
from tests.helpers import make_repo

REFUSAL = "fatal: detected dubious ownership in repository at 'X'\nTo add an exception..."


def test_git_refused_reads_the_ownership_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(git_module, "run_text", lambda *a, **k: Completed(128, "", REFUSAL))
    assert git_module.git_refused(tmp_path)
    monkeypatch.setattr(git_module, "run_text", lambda *a, **k: Completed(128, "", "other"))
    assert not git_module.git_refused(tmp_path)


def test_a_scan_warns_with_the_command_that_fixes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_repo(tmp_path, "admin")
    make_repo(tmp_path, "site")
    monkeypatch.setattr(scan_module, "repo_state", lambda root, timeout=10.0: (GitInfo(), None))
    monkeypatch.setattr(scan_module, "git_refused", lambda root: root.name == "admin")
    warnings = scan_module.scan_workspace(tmp_path).warnings
    refusal = [w for w in warnings if "safe.directory" in w]
    assert len(refusal) == 1 and "admin" in refusal[0] and "site" not in refusal[0]


def test_doctor_lists_repos_git_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_repo(tmp_path, "admin")
    assert CliRunner().invoke(app, ["scan", str(tmp_path)]).exit_code == 0
    monkeypatch.setattr(doctor, "git_refused", lambda root: root.name == "admin")
    out = CliRunner().invoke(app, ["doctor", str(tmp_path)]).output
    assert "WARN git trust:" in out and "safe.directory" in out and "admin" in out
