"""Phase 2e Task 10 (spec §20.4): packaging and version."""

import platform
import shutil
import subprocess
import tarfile
import tomllib
from importlib.metadata import version
from pathlib import Path

import pytest
from typer.testing import CliRunner

import cairn
from cairn.cli import app

ROOT = Path(__file__).resolve().parents[1]


def test_version_flag_reports_cairn_python_and_platform() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    first = result.output.splitlines()[0]
    assert first == f"cairn {cairn.__version__}"
    assert f"Python {platform.python_version()}" in result.output
    assert f"mcp {version('mcp')}" in result.output


def test_version_is_single_sourced() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert "version" not in project and "version" in project["dynamic"]
    assert version("cairnmap") == cairn.__version__


def test_metadata_is_release_ready() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["license"] == "Apache-2.0"
    assert set(project["license-files"]) == {"LICENSE", "NOTICE"}
    assert "Typing :: Typed" in project["classifiers"]
    assert any(c.startswith("Operating System :: OS Independent") for c in project["classifiers"])
    assert any(dep.startswith("mcp>=2.3,<3") for dep in project["dependencies"])
    assert (ROOT / "src" / "cairn" / "py.typed").is_file()


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not on PATH (CI has it)")
def test_sdist_ships_source_only(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    assert uv
    subprocess.run([uv, "build", "--sdist", "-o", str(tmp_path)], cwd=ROOT, check=True)
    (sdist,) = tmp_path.glob("*.tar.gz")
    with tarfile.open(sdist) as archive:
        names = [n.split("/", 1)[1] for n in archive.getnames() if "/" in n]
    assert any(n.startswith("src/cairn/") for n in names)
    # Tests need the benchmark suites and fixtures; packagers build from the git tag instead.
    unwanted = ("bench/", "docs/", "tests/", "fixtures/", ".superpowers/", ".github/")
    assert not any(n.startswith(unwanted) for n in names)
