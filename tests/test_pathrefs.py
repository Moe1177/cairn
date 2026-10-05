from pathlib import Path

from cairn.detectors.pathrefs import PathRefsDetector
from tests.helpers import ctx_for, make_repo, write


def _values(result) -> list[str]:
    return [f.value for f in result.consumes]


def test_tsconfig_and_makefile_refs(tmp_path: Path) -> None:
    write(tmp_path, "shared-ui/src/index.ts", "x")
    write(tmp_path, "money/go.mod", "module m")
    admin = make_repo(
        tmp_path, "admin",
        {"web/tsconfig.json": '{"compilerOptions": {"paths": {"@ui/*": ["../../shared-ui/src/*"]}}}',
         "Makefile": "test:\n\tcd ../money && go test ./...\n"},
    )
    result = PathRefsDetector().run(ctx_for(tmp_path, admin))
    assert _values(result) == ["money", "shared-ui/src"]
    assert result.consumes[0].evidence[0].file == "Makefile"


def test_ignores_own_repo_outside_workspace_and_missing(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    write(tmp_path, "outside/x.txt", "x")
    repo = make_repo(
        ws, "app",
        {"lib/a.ts": "x", "package.json": '{"scripts": {"a": "node ../app/lib/a.ts", "b": "cat ../../outside/x.txt", "c": "cd ../ghost"}}'},
    )
    assert _values(PathRefsDetector().run(ctx_for(ws, repo))) == []


def test_windows_backslashes(tmp_path: Path) -> None:
    write(tmp_path, "tools/run.ps1", "x")
    repo = make_repo(tmp_path, "app", {"scripts/build.ps1": "& ..\\..\\tools\\run.ps1\n"})
    assert _values(PathRefsDetector().run(ctx_for(tmp_path, repo))) == ["tools/run.ps1"]
