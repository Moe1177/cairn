import json
from pathlib import Path

from cairn.detectors.profile import MAX_LAYOUT, ProfileDetector
from cairn.model.graph import Command
from tests.helpers import ctx_for, make_repo, write

NEXT_PKG = json.dumps(
    {
        "name": "my-app",
        "scripts": {"dev": "next dev", "build": "next build", "test": "vitest", "format": "x"},
        "dependencies": {"next": "15", "react": "19", "drizzle-orm": "0.36", "@neondatabase/serverless": "0.10"},
        "devDependencies": {"typescript": "5"},
    }
)


def test_nested_next_app(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "shopapp", {"my-app/package.json": NEXT_PKG, "my-app/pnpm-lock.yaml": ""})
    for d in ("app", "lib", "db", "components", "zz-custom"):
        (repo / "my-app" / d).mkdir()
    result = ProfileDetector().run(ctx_for(tmp_path, repo, app_roots=[repo / "my-app"]))
    assert result.stack == ("typescript", "nextjs", "react", "drizzle", "neon")
    assert result.commands == (
        Command(name="dev", run="cd my-app && pnpm run dev"),
        Command(name="build", run="cd my-app && pnpm run build"),
        Command(name="test", run="cd my-app && pnpm run test"),
    )
    layout = {e.path: e.purpose for e in result.layout}
    assert layout["my-app/app/"] == "routes/pages"
    assert layout["my-app/db/"] == "database"
    assert layout["my-app/zz-custom/"] is None


def test_python_fastapi_with_tests_dir(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path, "orders-svc",
        {"pyproject.toml": '[project]\nname = "orders-svc"\ndependencies = ["FastAPI>=0.110"]\n'},
    )
    (repo / "tests").mkdir()
    result = ProfileDetector().run(ctx_for(tmp_path, repo))
    assert result.stack == ("python", "fastapi")
    assert result.commands == (Command(name="test", run="pytest"),)


def test_go_rust_java(tmp_path: Path) -> None:
    go = make_repo(tmp_path, "payments", {"go.mod": "module x\nrequire github.com/gin-gonic/gin v1.9.0\n"})
    rs = make_repo(tmp_path, "ledger", {"Cargo.toml": '[package]\nname = "ledger"\n'})
    jv = make_repo(tmp_path, "billing", {"pom.xml": "<project/>"})
    assert ProfileDetector().run(ctx_for(tmp_path, go)).stack == ("go", "gin")
    assert ProfileDetector().run(ctx_for(tmp_path, rs)).commands[0] == Command(name="test", run="cargo test")
    assert ProfileDetector().run(ctx_for(tmp_path, jv)).stack == ("java",)


def test_multiple_app_roots_prefix_command_names(tmp_path: Path) -> None:
    pkg = json.dumps({"scripts": {"dev": "x"}})
    repo = make_repo(tmp_path, "mono", {"web/package.json": pkg, "admin/package.json": pkg})
    ctx = ctx_for(tmp_path, repo, app_roots=[repo / "admin", repo / "web"])
    names = [c.name for c in ProfileDetector().run(ctx).commands]
    assert names == ["admin:dev", "web:dev"]


def test_layout_is_capped_and_skips_hidden_and_ignored(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "big")
    for i in range(20):
        (repo / f"dir{i:02d}").mkdir()
    write(repo, ".github/workflows/ci.yml", "x")
    write(repo, "node_modules/x/index.js", "x")
    layout = ProfileDetector().run(ctx_for(tmp_path, repo)).layout
    assert len(layout) == MAX_LAYOUT
    assert all(not e.path.startswith((".", "node_modules")) for e in layout)


def test_no_manifest_gives_empty_stack(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "notes-only", {"notes.md": "x"})
    result = ProfileDetector().run(ctx_for(tmp_path, repo))
    assert result.stack == () and result.commands == ()
