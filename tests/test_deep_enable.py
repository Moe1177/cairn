"""0.7 A1: graphify in one command; refresh keeps deep indexes fresh by default."""

import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cairn import deep as deep_ops
from cairn import providers
from cairn.cli import app
from cairn.providers.graphify import GraphifyProvider
from tests.test_deep_surfaces import ws  # noqa: F401  (fixture: two repos, a fake graphify)
from tests.test_graphify_provider import _fake_graphify


def _cli(*args: str) -> str:
    result = CliRunner().invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result.output


@pytest.mark.parametrize(
    ("tools", "first"),
    [({"uv"}, "uv"), ({"pipx"}, "pipx"), (set(), "pip")],
)
def test_the_install_command_fits_what_is_available(
    monkeypatch: pytest.MonkeyPatch, tools: set[str], first: str
) -> None:
    monkeypatch.setattr(deep_ops.shutil, "which", lambda name: name if name in tools else None)
    command = deep_ops.graphify_install_command()
    assert first in " ".join(command)
    assert any("graphifyy" in part and "<0.10" in part for part in command)


def test_enable_installs_then_builds_every_index(
    ws: Path,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = GraphifyProvider(executable=str(tmp_path / "nope"))
    installed = GraphifyProvider(executable=_fake_graphify(tmp_path))
    state = {"provider": missing}
    monkeypatch.setattr(providers, "default_provider", lambda: state["provider"])
    ran: list[list[str]] = []

    def fake_install(command: list[str]) -> int:
        ran.append(command)
        state["provider"] = installed
        return 0

    monkeypatch.setattr(deep_ops, "run_installer", fake_install)
    out = _cli("deep", "enable", "--yes", "-w", str(ws))
    assert ran and "graphifyy" in " ".join(ran[0])
    assert "app: 1 symbols indexed" in out and "billing: 1 symbols indexed" in out


def test_enable_without_yes_asks_first(
    ws: Path,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        providers, "default_provider", lambda: GraphifyProvider(executable=str(tmp_path / "x"))
    )
    monkeypatch.setattr(deep_ops, "run_installer", lambda command: pytest.fail("ran unasked"))
    result = CliRunner().invoke(app, ["deep", "enable", "-w", str(ws)], input="n\n")
    assert result.exit_code == 1 and "graphifyy" in result.output


def test_refresh_rebuilds_stale_deep_indexes_by_default(ws: Path) -> None:  # noqa: F811
    _cli("deep", "build", "app", "-w", str(ws))
    meta = ws / ".cairn" / "deep" / "app" / "cairn-deep.json"
    built = meta.stat().st_mtime_ns
    time.sleep(1.1)
    (ws / "app" / "auth.py").write_text("def login():\n    return 9\n", encoding="utf-8")
    _cli("refresh", "--no-deep", str(ws))
    assert meta.stat().st_mtime_ns == built
    _cli("refresh", str(ws))
    assert meta.stat().st_mtime_ns != built


def test_refresh_without_deep_indexes_never_needs_graphify(
    ws: Path,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        providers, "default_provider", lambda: GraphifyProvider(executable=str(tmp_path / "x"))
    )
    assert "Mapped" in _cli("refresh", str(ws))


def test_a_build_in_progress_is_not_started_twice(ws: Path) -> None:  # noqa: F811
    lock = ws / ".cairn" / "deep" / "app" / deep_ops.BUILD_LOCK
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("", encoding="utf-8")
    out = CliRunner().invoke(app, ["deep", "build", "app", "-w", str(ws)]).output
    assert "already being built" in out


def test_doctor_reports_deep_coverage(ws: Path) -> None:  # noqa: F811
    _cli("deep", "build", "app", "-w", str(ws))
    out = _cli("doctor", str(ws))
    assert "deep indexes: 1 of 2 repos" in out
