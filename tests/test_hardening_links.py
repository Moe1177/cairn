"""Phase 2e Task 2 (audit H2, M6): never read or write through links out of a repo."""

import json
import os
from pathlib import Path

import pytest

from cairn.emit import write_outputs
from cairn.integrations.harnesses import install_harness
from cairn.scan import scan_workspace
from tests.helpers import make_repo, write

SECRET = "admin password is Winter2026Payroll"


def _dir_link(link: Path, target: Path) -> None:
    """A directory junction on Windows (no privileges needed), a symlink elsewhere."""
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def _outside(tmp_path: Path) -> Path:
    outside = tmp_path / "outside"
    write(outside, "README.md", f"# private\n\n{SECRET}, keep it safe.\n")
    write(outside, "package.json", json.dumps({"name": "private-pkg"}))
    write(outside, "schema.sql", "CREATE TABLE payroll_secrets (id int);\n")
    return outside


def _all_outputs(ws: Path) -> str:
    cairn = ws / ".cairn"
    texts = [p.read_text(encoding="utf-8") for p in cairn.rglob("*") if p.is_file()]
    claude_md = ws / "CLAUDE.md"
    return "\n".join(
        texts + ([claude_md.read_text(encoding="utf-8")] if claude_md.exists() else [])
    )


def test_linked_folder_inside_a_repo_is_not_read(tmp_path: Path) -> None:
    # audit H2: `repo/pkg` -> a folder outside the workspace
    outside = _outside(tmp_path)
    ws = tmp_path / "ws"
    make_repo(ws, "jrepo", {"README.md": "# jrepo\n\nThe j service.\n"})
    _dir_link(ws / "jrepo" / "pkg", outside)
    _dir_link(ws / "jrepo" / "db", outside)
    write_outputs(ws, scan_workspace(ws))
    text = _all_outputs(ws)
    assert "Winter2026Payroll" not in text
    assert "payroll_secrets" not in text and "private-pkg" not in text


def test_symlinked_file_inside_a_repo_is_not_read(tmp_path: Path) -> None:
    # audit H2 (POSIX form): README.md -> ../../.env-like file
    outside = _outside(tmp_path)
    ws = tmp_path / "ws"
    repo = make_repo(ws, "frepo")
    try:
        (repo / "README.md").symlink_to(outside / "README.md")
    except OSError:
        pytest.skip("file symlinks need extra privileges on this Windows machine")
    write_outputs(ws, scan_workspace(ws))
    assert "Winter2026Payroll" not in _all_outputs(ws)


def test_cursor_rule_is_not_written_through_a_linked_folder(tmp_path: Path) -> None:
    # audit M6: a committed `.cursor` link must not let cairn write outside the repo.
    outside = tmp_path / "outside"
    outside.mkdir()
    ws = tmp_path / "ws"
    repo = make_repo(ws, "crepo")
    (repo / ".git" / "info").mkdir(parents=True)
    _dir_link(repo / ".cursor", outside)
    safe = make_repo(ws, "safe")
    (safe / ".git" / "info").mkdir(parents=True)
    write_outputs(ws, scan_workspace(ws))
    lines = install_harness("cursor", ws, per_repo=True)
    assert not any(outside.rglob("*.mdc"))
    assert (safe / ".cursor" / "rules" / "cairn.mdc").is_file()
    assert any("crepo" in line and "link" in line for line in lines)
