"""Phase 2d Task 2: packages inside monorepos (spec §21.4)."""

import json
from pathlib import Path

from cairn.discover.workspaces import workspace_packages
from cairn.emit import write_outputs
from cairn.mcp_server import tools
from cairn.model.graph import EdgeType
from cairn.paths import cards_dir
from cairn.scan import scan_workspace
from tests.helpers import make_repo, write
from tests.test_hardening_links import _dir_link


def _pkg(root: Path, rel: str, name: str) -> None:
    write(root, f"{rel}/package.json", json.dumps({"name": name}))


def _names(root: Path) -> list[tuple[str, str]]:
    return [(p.name, p.path) for p in workspace_packages(root)]


def test_pnpm_globs_with_negation(tmp_path: Path) -> None:
    root = make_repo(tmp_path, "platform", {"package.json": json.dumps({"name": "platform"})})
    write(
        root,
        "pnpm-workspace.yaml",
        "packages:\n  - 'packages/*'\n  - 'apps/**'\n  - '!packages/legacy'\n",
    )
    _pkg(root, "packages/ui", "@acme/ui")
    _pkg(root, "packages/legacy", "@acme/legacy")
    _pkg(root, "apps/web", "@acme/web")
    _pkg(root, "apps/tools/cli", "@acme/cli")
    assert _names(root) == [
        ("@acme/cli", "apps/tools/cli"),
        ("@acme/web", "apps/web"),
        ("@acme/ui", "packages/ui"),
    ]


def test_npm_workspaces_object_form(tmp_path: Path) -> None:
    root = make_repo(
        tmp_path, "mono", {"package.json": json.dumps({"workspaces": {"packages": ["libs/*"]}})}
    )
    _pkg(root, "libs/a", "@m/a")
    assert _names(root) == [("@m/a", "libs/a")]


def test_cargo_go_and_uv_workspaces(tmp_path: Path) -> None:
    cargo = make_repo(tmp_path, "rusty", {"Cargo.toml": '[workspace]\nmembers = ["crates/*"]\n'})
    write(cargo, "crates/core/Cargo.toml", '[package]\nname = "rusty-core"\n')
    assert _names(cargo) == [("rusty-core", "crates/core")]
    gow = make_repo(tmp_path, "goes", {"go.work": "go 1.22\n\nuse (\n\t./svc/api\n\t./lib\n)\n"})
    write(gow, "svc/api/go.mod", "module github.com/acme/api\n")
    write(gow, "lib/go.mod", "module github.com/acme/lib\n")
    assert _names(gow) == [("lib", "lib"), ("api", "svc/api")]
    uv = make_repo(
        tmp_path, "pyws", {"pyproject.toml": '[tool.uv.workspace]\nmembers = ["packages/*"]\n'}
    )
    write(uv, "packages/core/pyproject.toml", '[project]\nname = "acme-core"\n')
    assert _names(uv) == [("acme-core", "packages/core")]


def test_linked_package_dirs_are_skipped(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    _pkg(outside, ".", "@evil/pkg")
    root = make_repo(tmp_path, "mono", {"package.json": json.dumps({"workspaces": ["packages/*"]})})
    _pkg(root, "packages/real", "@m/real")
    _dir_link(root / "packages" / "linked", outside)
    assert _names(root) == [("@m/real", "packages/real")]


def test_package_count_is_capped(tmp_path: Path) -> None:
    root = make_repo(tmp_path, "huge", {"package.json": json.dumps({"workspaces": ["p/*"]})})
    for i in range(300):
        _pkg(root, f"p/x{i:03d}", f"@h/x{i:03d}")
    assert len(workspace_packages(root)) == 200


def _monorepo_workspace(tmp_path: Path) -> Path:
    platform = make_repo(
        tmp_path, "platform", {"package.json": json.dumps({"name": "platform", "private": True})}
    )
    write(platform, "pnpm-workspace.yaml", "packages:\n  - packages/*\n")
    _pkg(platform, "packages/ui", "@acme/ui")
    _pkg(platform, "packages/config", "@acme/config")
    make_repo(
        tmp_path,
        "web",
        {"package.json": json.dumps({"name": "web", "dependencies": {"@acme/ui": "^1.0.0"}})},
    )
    return tmp_path


def test_sibling_depending_on_a_monorepo_package_links_to_the_monorepo(tmp_path: Path) -> None:
    ws = _monorepo_workspace(tmp_path)
    result = scan_workspace(ws)
    edges = {(e.source, e.target, e.type) for e in result.workspace.edges}
    assert ("web", "platform", EdgeType.DEPENDS_ON_PACKAGE) in edges
    platform = result.workspace.repo("platform")
    assert platform is not None
    assert [(p.name, p.path) for p in platform.packages] == [
        ("@acme/config", "platform/packages/config"),
        ("@acme/ui", "platform/packages/ui"),
    ]


def test_card_and_mcp_know_packages(tmp_path: Path) -> None:
    ws = _monorepo_workspace(tmp_path)
    write_outputs(ws, scan_workspace(ws))
    card = (cards_dir(ws) / "platform.md").read_text(encoding="utf-8")
    assert "## Packages" in card and "@acme/ui → platform/packages/ui" in card
    answer = tools.resolve_text(ws, "@acme/ui")
    assert "platform" in answer and "platform/packages/ui" in answer
    assert "# platform" in tools.card_text(ws, "@acme/ui")
