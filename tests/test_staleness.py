import subprocess
from pathlib import Path

from typer.testing import CliRunner

from cairn.authored_store import set_summary
from cairn.cli import app
from cairn.discover.git import summary_is_stale
from cairn.emit import write_outputs
from cairn.render.card import render_card
from cairn.scan import scan_workspace


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
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
        text=True,
    ).stdout.strip()


def _commit(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", rel)


def test_summary_staleness_rules(materialize) -> None:
    ws = materialize("mini-eats").resolve()
    repo = ws / "notes"
    sha = _git(repo, "rev-parse", "--short", "HEAD")
    _commit(repo, "notes/small.py", "x = 1\n")
    assert summary_is_stale(repo, sha, threshold=50) is False
    _commit(repo, "pyproject.toml", '[project]\nname = "notes"\nversion = "0.2.0"\n')
    assert summary_is_stale(repo, sha, threshold=50) is True  # manifest changed
    assert summary_is_stale(repo, "deadbeef", threshold=50) is True  # unknown sha


def test_many_changed_files_make_a_summary_stale(materialize) -> None:
    ws = materialize("mini-eats").resolve()
    repo = ws / "notes"
    sha = _git(repo, "rev-parse", "--short", "HEAD")
    for i in range(3):
        _commit(repo, f"notes/m{i}.py", "x = 1\n")
    assert summary_is_stale(repo, sha, threshold=2) is True


def test_stale_summary_is_flagged_on_card_and_status(materialize, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CAIRN_HOME", str(tmp_path / "ch"))
    ws = materialize("mini-eats").resolve()
    write_outputs(ws, scan_workspace(ws))
    set_summary(ws, "notes", "Study notes.")
    _commit(ws / "notes", "docs/new.md", "# new top-level folder\n")
    result = scan_workspace(ws)
    repo = result.workspace.repo("notes")
    assert repo.summary_stale is True
    card = render_card(repo, result.workspace, authored=result.authored["notes"])
    assert "(possibly stale: written at" in card
    write_outputs(ws, result)
    status = CliRunner().invoke(app, ["status", str(ws)]).output
    assert "Possibly stale summaries: notes" in status
