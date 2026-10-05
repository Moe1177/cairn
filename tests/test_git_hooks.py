import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cairn.cli import app
from cairn.emit import write_outputs
from cairn.integrations.git_hooks import install_hooks, uninstall_hooks
from cairn.scan import scan_workspace
from tests.helpers import make_repo


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    make_repo(tmp_path, "alpha")
    make_repo(tmp_path, "beta")
    write_outputs(tmp_path, scan_workspace(tmp_path))
    return tmp_path


def test_hooks_install_and_uninstall(ws: Path) -> None:
    assert install_hooks(ws) == 2
    hook = ws / "alpha" / ".git" / "hooks" / "post-commit"
    text = hook.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/sh\n") and "# cairn:start" in text
    assert "refresh" in text and "--quiet" in text
    if os.name != "nt":
        assert os.access(hook, os.X_OK)
    install_hooks(ws)
    assert hook.read_text(encoding="utf-8").count("# cairn:start") == 1
    assert uninstall_hooks(ws) == 2
    assert not hook.exists()


def test_existing_hook_is_preserved(ws: Path) -> None:
    # Review Focus 3
    hook = ws / "beta" / ".git" / "hooks" / "post-merge"
    hook.parent.mkdir(parents=True)
    original = "#!/bin/sh\ngraphify update --quiet\n"
    hook.write_text(original, encoding="utf-8", newline="")
    install_hooks(ws)
    assert "graphify update" in hook.read_text(encoding="utf-8")
    uninstall_hooks(ws)
    assert hook.read_text(encoding="utf-8") == original


def test_hooks_cli(ws: Path) -> None:
    runner = CliRunner()
    assert (
        "git hooks installed in 2 repos" in runner.invoke(app, ["hooks", "install", str(ws)]).output
    )
    bad = runner.invoke(app, ["hooks", "maybe", str(ws)])
    assert bad.exit_code == 1 and "cairn hooks install" in bad.output
