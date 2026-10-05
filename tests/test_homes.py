import subprocess
import sys
from pathlib import Path

import cairn.integrations.server_command as sc
from cairn.integrations.homes import claude_home, codex_home, cursor_home, gemini_home, user_home


def test_homes_follow_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CAIRN_USER_HOME", str(tmp_path))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    assert user_home() == tmp_path
    assert claude_home() == tmp_path / ".claude"
    assert codex_home() == tmp_path / ".codex"
    assert gemini_home() == tmp_path / ".gemini"
    assert cursor_home() == tmp_path / ".cursor"
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "cx"))
    assert codex_home() == tmp_path / "cx"


def test_server_command_prefers_installed_cli(monkeypatch, tmp_path: Path) -> None:
    exe = tmp_path / "cairn.exe"
    exe.write_text("")
    monkeypatch.setattr(sc.shutil, "which", lambda name: str(exe))
    assert sc.server_command() == [str(exe.resolve()), "serve"]
    monkeypatch.setattr(sc.shutil, "which", lambda name: None)
    assert sc.server_command() == [sys.executable, "-m", "cairn", "serve"]


def test_python_dash_m_cairn_runs_the_cli() -> None:
    out = subprocess.run([sys.executable, "-m", "cairn", "--help"], capture_output=True, text=True)
    assert out.returncode == 0 and "scan" in out.stdout
