"""Phase 2e Task 5 (audit M3, L2, L3; cross-OS 2): one safe subprocess runner."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from cairn.bench.workspace import materialize
from cairn.discover.files import iter_files
from cairn.discover.git import git_info, normalize_remote
from cairn.integrations.harnesses import _claude_cli
from cairn.scan import scan_workspace


def _git_repo(tmp_path: Path) -> Path:
    src = tmp_path / "src" / "app"
    src.mkdir(parents=True)
    (src / ".fixture-repo").write_text("", encoding="utf-8")
    (src / "a.txt").write_text("a", encoding="utf-8")
    return materialize(tmp_path / "src", tmp_path / "ws") / "app"


def test_repo_fsmonitor_command_never_runs(tmp_path: Path) -> None:
    # audit M3: `git status` runs core.fsmonitor; a copied repo could carry one.
    repo = _git_repo(tmp_path)
    marker = tmp_path / "PWNED"
    script = tmp_path / "hook.py"
    script.write_text(f"open(r'{marker}', 'w').write('x')\n", encoding="utf-8")
    command = f'"{Path(sys.executable).as_posix()}" "{script.as_posix()}"'
    subprocess.run(["git", "-C", str(repo), "config", "core.fsmonitor", command], check=True)
    git_info(repo)
    scan_workspace(repo.parent)
    assert not marker.exists()


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://[x", None),
        ("https://user:pa/ss@host.example/acme/web.git", "host.example/acme/web"),
        ("https://u:p@ss@github.com/acme/api", "github.com/acme/api"),
        ("https://github.com/acme/web.git", "github.com/acme/web"),
        ("git@github.com:acme/web.git", "github.com/acme/web"),
    ],
)
def test_remote_parsing_never_raises_or_leaks(url: str, expected: str | None) -> None:
    # audit L2
    assert normalize_remote(url) == expected


def test_claude_cli_output_is_utf8(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # cross-OS 2: the locale codec (cp1252) can't decode byte 0x81 ("Ł" in UTF-8).
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    code = "import sys; sys.stdout.buffer.write('\\u0141ukasz ok'.encode())"
    if os.name == "nt":
        (bin_dir / "claude.cmd").write_text(f'@"{sys.executable}" -c "{code}"\n', encoding="utf-8")
    else:
        shim = bin_dir / "claude"
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" -c "{code}"\n', encoding="utf-8")
        shim.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    result = _claude_cli(["--version"])
    assert result is not None and "Łukasz ok" in result[1]


def test_root_gitignore_read_is_capped(tmp_path: Path) -> None:
    # audit L3: a huge .gitignore is read only up to the cap.
    (tmp_path / ".gitignore").write_text("# pad\n" * 400_000 + "hidden/\n", encoding="utf-8")
    (tmp_path / "hidden").mkdir()
    (tmp_path / "hidden" / "x.txt").write_text("x", encoding="utf-8")
    names = {p.relative_to(tmp_path).as_posix() for p in iter_files(tmp_path)}
    assert "hidden/x.txt" in names  # the rule past the cap was never read
