"""Spec §27.1: the plugin's shell scripts, run with a real bash, with and without uv."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import cairn

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "cairn"
PIN = f"cairnmap=={cairn.__version__}"


def _bash() -> tuple[str, str] | None:
    """(bash, a PATH with the basic tools and no uv), or None. On Windows only Git Bash:
    System32's bash.exe is WSL, which can't see this checkout the same way."""
    if os.name == "nt":
        git = shutil.which("git")
        if not git:
            return None
        # git.exe sits in Git\cmd or Git\mingw64\bin; bash.exe in Git\bin.
        root = next(
            (p for p in Path(git).resolve().parents if (p / "bin" / "bash.exe").is_file()), None
        )
        return (str(root / "bin" / "bash.exe"), str(root / "usr" / "bin")) if root else None
    bash = shutil.which("bash")
    return (bash, "/usr/bin:/bin") if bash else None


BASH = _bash()
pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash (Git Bash on Windows)")


def _run(script: Path, home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    assert BASH is not None
    bash, path = BASH
    env = {
        "PATH": path,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
    }
    return subprocess.run(
        [bash, str(script), *args], capture_output=True, text=True, env=env, timeout=60, check=False
    )


def _fake_uvx(home: Path) -> None:
    """A uvx where uv's installer puts it, which reports how it was called."""
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    uvx = bin_dir / "uvx"
    uvx.write_text(
        '#!/usr/bin/env bash\necho "ARGS:$*"\necho "PLUGIN:${CAIRN_PLUGIN:-unset}"\n',
        encoding="utf-8",
        newline="\n",
    )
    uvx.chmod(0o755)


def test_without_uv_the_hook_warns_the_user_and_asks_claude_to_offer_an_install(
    tmp_path: Path,
) -> None:
    result = _run(PLUGIN / "scripts" / "session-start.sh", tmp_path)
    assert result.returncode == 0
    assert "uv isn't installed" in result.stderr  # shown to the user
    output = json.loads(result.stdout)
    assert "uv isn't installed" in output["systemMessage"]
    hook = output["hookSpecificOutput"]
    assert hook["hookEventName"] == "SessionStart"
    context = hook["additionalContext"]
    assert "offer once to install uv" in context and "only if the user agrees" in context
    assert "astral.sh/uv/install" in context and "restart Claude Code" in context


def test_a_uv_installed_during_the_session_is_found_where_its_installer_put_it(
    tmp_path: Path,
) -> None:
    _fake_uvx(tmp_path)  # not on PATH: Claude Code's PATH predates the install
    result = _run(PLUGIN / "scripts" / "session-start.sh", tmp_path)
    assert result.returncode == 0
    assert f"ARGS:--from {PIN} cairn context" in result.stdout


def test_the_wrapper_runs_the_pinned_cairn_and_says_it_is_the_plugin(tmp_path: Path) -> None:
    _fake_uvx(tmp_path)
    result = _run(PLUGIN / "bin" / "cairn", tmp_path, "status", "--help")
    assert f"ARGS:--from {PIN} cairn status --help" in result.stdout
    assert "PLUGIN:1" in result.stdout


def test_without_uv_the_wrapper_says_how_to_get_it(tmp_path: Path) -> None:
    result = _run(PLUGIN / "bin" / "cairn", tmp_path, "status")
    assert result.returncode == 127
    assert "astral.sh/uv/install" in result.stderr and f"pipx install {PIN}" in result.stderr


def test_every_script_pins_the_release_this_plugin_ships_with() -> None:
    lookup = (PLUGIN / "scripts" / "find-uvx.sh").read_text(encoding="utf-8")
    assert f'CAIRN_PIN="{PIN}"' in lookup
