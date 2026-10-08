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


def _env(home: Path, path: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    return {
        "PATH": path,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "APPDATA": str(home / "AppData" / "Roaming"),
        "LOCALAPPDATA": str(home / "AppData" / "Local"),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        **(extra or {}),
    }


def _run(
    script: Path,
    home: Path,
    *args: str,
    on_path: Path | None = None,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run `script` with a bare PATH (plus `on_path`, if given), `home` as the user's home, and
    `env` on top."""
    assert BASH is not None
    bash, path = BASH
    path = f"{on_path}{os.pathsep}{path}" if on_path else path
    return subprocess.run(
        [bash, str(script), *args],
        capture_output=True,
        text=True,
        env=_env(home, path, env),
        cwd=cwd,
        timeout=60,
        check=False,
    )


def _fake_uvx(home: Path, where: str = ".local/bin") -> Path:
    """A uvx in `where` under `home` (default: where uv's installer puts it), which reports
    how it was called. Returns its folder."""
    bin_dir = home / where
    bin_dir.mkdir(parents=True)
    uvx = bin_dir / "uvx"
    uvx.write_text(
        '#!/usr/bin/env bash\necho "ARGS:$*"\necho "PLUGIN:${CAIRN_PLUGIN:-unset}"\n',
        encoding="utf-8",
        newline="\n",
    )
    uvx.chmod(0o755)
    return bin_dir


def test_without_uv_the_hook_warns_the_user_and_asks_claude_to_offer_an_install(
    tmp_path: Path,
) -> None:
    result = _run(PLUGIN / "scripts" / "session-start.sh", tmp_path)
    assert result.returncode == 0
    assert "couldn't find uv" in result.stderr  # shown to the user
    output = json.loads(result.stdout)
    assert "couldn't find uv" in output["systemMessage"]
    hook = output["hookSpecificOutput"]
    assert hook["hookEventName"] == "SessionStart"
    context = hook["additionalContext"]
    assert "offer once to install uv" in context and "only if the user agrees" in context
    assert "astral.sh/uv/install" in context and "restart Claude Code" in context
    assert "isn't on PATH" in context  # uv may be installed but unreachable


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


def test_a_uv_on_path_is_run_by_name(tmp_path: Path) -> None:
    folder = _fake_uvx(tmp_path, "tools")  # nowhere the fallback looks
    result = _run(PLUGIN / "scripts" / "session-start.sh", tmp_path, on_path=folder)
    assert result.returncode == 0
    assert f"ARGS:--from {PIN} cairn context" in result.stdout


def test_the_mcp_server_runs_the_pinned_cairn_for_the_project_folder(tmp_path: Path) -> None:
    _fake_uvx(tmp_path)
    serve = PLUGIN / "scripts" / "mcp-serve"
    result = _run(serve, tmp_path, env={"CLAUDE_PROJECT_DIR": "/work/api"})
    assert result.returncode == 0
    # Nothing else on stdout: it is the MCP channel.
    assert result.stdout.splitlines() == [
        f"ARGS:--from {PIN} cairn serve --from /work/api",
        "PLUGIN:1",
    ]
    project = tmp_path / "project"
    project.mkdir()
    result = _run(serve, tmp_path, cwd=project)  # no CLAUDE_PROJECT_DIR: the folder it runs in
    (args, _) = result.stdout.splitlines()
    assert args.startswith(f"ARGS:--from {PIN} cairn serve --from /")
    assert args.endswith("/project")  # bash's form of the path (/c/... under Git Bash)


@pytest.mark.skipif(os.name == "nt", reason="Windows runs mcp-serve.cmd instead")
def test_claude_code_can_start_the_mcp_server_as_a_program(tmp_path: Path) -> None:
    """.mcp.json names the script itself, so it runs through its shebang, not `bash script`."""
    _fake_uvx(tmp_path)
    result = subprocess.run(
        [str(PLUGIN / "scripts" / "mcp-serve")],
        capture_output=True,
        text=True,
        env=_env(tmp_path, "/usr/bin:/bin", {"CLAUDE_PROJECT_DIR": "/work/api"}),
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0] == f"ARGS:--from {PIN} cairn serve --from /work/api"


def test_without_uv_the_mcp_server_fails_with_how_to_get_it(tmp_path: Path) -> None:
    result = _run(PLUGIN / "scripts" / "mcp-serve", tmp_path, env={"CLAUDE_PROJECT_DIR": "/w"})
    assert result.returncode == 127 and result.stdout == ""
    assert "couldn't find uv" in result.stderr and "astral.sh/uv/install" in result.stderr


def test_every_script_spells_out_uvx_and_the_pin() -> None:
    for script in ("scripts/session-start.sh", "scripts/mcp-serve", "bin/cairn"):
        text = (PLUGIN / script).read_text(encoding="utf-8")
        assert f"exec uvx --from {PIN} cairn" in text, script
    windows = (PLUGIN / "scripts" / "mcp-serve.cmd").read_text(encoding="utf-8")
    assert f'uvx --from {PIN} cairn serve --from "%CLAUDE_PROJECT_DIR%" %*' in windows


# --- Windows runs scripts/mcp-serve.cmd in place of the bash script -------------------------

windows_only = pytest.mark.skipif(os.name != "nt", reason="cmd.exe runs only on Windows")


def _run_cmd(home: Path, on_path: Path | None = None) -> subprocess.CompletedProcess[str]:
    system32 = str(Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32")
    path = f"{on_path}{os.pathsep}{system32}" if on_path else system32
    env = _env(home, path, {"CLAUDE_PROJECT_DIR": r"C:\work\api"})
    return subprocess.run(
        ["cmd", "/d", "/c", str(PLUGIN / "scripts" / "mcp-serve.cmd")],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )


@windows_only
def test_on_windows_the_mcp_server_runs_the_pinned_cairn_for_the_project_folder(
    tmp_path: Path,
) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "uvx.cmd").write_text(
        "@echo ARGS:%*\r\n@echo PLUGIN:%CAIRN_PLUGIN%\r\n", encoding="utf-8", newline=""
    )
    result = _run_cmd(tmp_path, on_path=tools)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == [
        "ARGS:--from",
        PIN,
        "cairn",
        "serve",
        "--from",
        r'"C:\work\api"',
        "PLUGIN:1",
    ]


@windows_only
def test_on_windows_without_uv_the_mcp_server_fails_with_how_to_get_it(tmp_path: Path) -> None:
    result = _run_cmd(tmp_path)
    assert result.returncode == 127 and result.stdout == ""
    assert "couldn't find uv" in result.stderr and "astral.sh/uv/install.ps1" in result.stderr


@pytest.mark.parametrize(
    "where",
    [
        "AppData/Roaming/Python/Python312/Scripts",  # pip install --user uv, Windows
        "AppData/Local/Programs/Python/Python313/Scripts",  # pip into a python.org install
        "Library/Python/3.12/bin",  # pip install --user uv, macOS
        ".cargo/bin",
    ],
)
def test_a_pip_installed_uv_off_path_is_still_found(tmp_path: Path, where: str) -> None:
    _fake_uvx(tmp_path, where)
    result = _run(PLUGIN / "scripts" / "session-start.sh", tmp_path)
    assert result.returncode == 0
    assert f"ARGS:--from {PIN} cairn context" in result.stdout
