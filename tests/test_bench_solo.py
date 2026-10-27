import json
import shutil
from collections.abc import Sequence
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

import cairn.bench.solo as solo
from cairn.bench.grading import grade, org_paths
from cairn.bench.run import regrade_log, run_bench
from cairn.bench.runner import FakeRunner
from cairn.bench.suite import Task, load_suite
from cairn.bench.workspace import materialize
from cairn.cli import app
from cairn.config import OrgSource
from cairn.errors import CairnError
from cairn.paths import config_file

SUITE = Path(__file__).resolve().parents[1] / "bench" / "suites" / "shopverse"
ORG = OrgSource(org="shopverse")
REPOS = {"storefront", "orders-svc", "admin", "payments-svc", "shared-types"}


def suite_with_org(tmp_path: Path, org: str | None = "shopverse") -> Path:
    suite = tmp_path / "suite"
    shutil.copytree(SUITE, suite)
    if org is not None:
        data = yaml.safe_load((suite / "suite.yaml").read_text(encoding="utf-8"))
        data["org"] = {"org": org}
        (suite / "suite.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    return suite


def no_drift(cache_ws: Path, org: OrgSource, tasks: Sequence[Task]) -> dict[str, list[str]]:
    return {}


@pytest.fixture(autouse=True)
def homes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAIRN_HOME", str(tmp_path / "ch"))
    monkeypatch.setenv("CAIRN_USER_HOME", str(tmp_path / "uh"))


def reply_json(answer: str) -> str:
    return json.dumps({"result": answer, "num_turns": 1, "duration_ms": 1500})


def test_each_session_sees_only_its_own_repo(tmp_path: Path) -> None:
    seen: list[tuple[str, set[str], bool, str]] = []

    def reply(prompt: str, cwd: Path) -> str:
        ws = cwd.parent
        repos = {p.name for p in ws.iterdir() if (p / ".git").exists()}
        config = config_file(ws)
        orgs = config.read_text(encoding="utf-8") if config.is_file() else ""
        seen.append((cwd.name, repos, (ws / "CLAUDE.md").is_file(), orgs))
        if "refund" in prompt:  # read through the org tools, which print owner/repo/path
            return reply_json("The refunds live in shopverse/orders-svc/app/refunds.py.")
        return reply_json(f"{(cwd / 'lib' / 'cart.ts').as_posix()}")  # its own copy, absolute

    out = tmp_path / "out"
    records = run_bench(
        suite_with_org(tmp_path),
        conditions=("A", "D"),
        runs=1,
        task_ids=("refund-logic", "cart-total"),
        runner=FakeRunner(reply),
        out_dir=out,
        now="20261027-120000",
        scope="repo",
        org_setup=no_drift,
    )
    assert [(r.condition, r.task_id, r.grade.success) for r in records] == [
        ("A", "refund-logic", True),
        ("A", "cart-total", True),
        ("D", "refund-logic", True),
        ("D", "cart-total", True),
    ]
    assert all(repos == {cwd} for cwd, repos, _, _ in seen)
    assert [(cwd, mapped) for cwd, _, mapped, _ in seen] == [
        ("admin", False),
        ("storefront", False),
        ("admin", True),
        ("storefront", True),
    ]
    assert "org: shopverse" in seen[2][3] and seen[0][3] == ""  # A has no map, so no config
    header = json.loads((out / "20261027-120000.jsonl").read_text(encoding="utf-8").split("\n")[0])
    assert header["_header"]["scope"] == "repo"
    assert "Time (s)" in (out / "20261027-120000.md").read_text(encoding="utf-8")


def test_repo_scope_gives_condition_e_a_server_on_the_solo_workspace(tmp_path: Path) -> None:
    import cairn.bench.run as run_module

    servers: list[dict] = []
    seen: list[tuple[Path, tuple[Path, ...]]] = []
    whole: list[bool] = []

    class Recording(FakeRunner):
        def run(self, prompt, cwd, ws, mcp_config, hidden=()):  # type: ignore[no-untyped-def]
            assert mcp_config is not None and ws == cwd.parent  # --add-dir: the solo workspace
            servers.append(json.loads(mcp_config.read_text(encoding="utf-8"))["mcpServers"])
            seen.append((cwd, tuple(hidden)))
            # while the run's folders still exist: one of them holds every repo
            whole.append(any((f / "ws" / "orders-svc").is_dir() for f in hidden))
            return super().run(prompt, cwd, ws, mcp_config, hidden)

    suite = suite_with_org(tmp_path)
    run_bench(
        suite,
        conditions=("E",),
        runs=1,
        task_ids=("cart-total", "refund-logic"),
        runner=Recording(lambda prompt, cwd: reply_json("lib/cart.ts")),
        out_dir=tmp_path / "out",
        now="x",
        scope="repo",
        org_setup=no_drift,
    )
    server = servers[0]["cairn"]
    workspace = Path(server["args"][server["args"].index("--workspace") + 1])
    assert workspace.name == "ws" and workspace.parent.name.startswith("cairn-bench-solo-")
    assert run_module._RUN_WS.search(workspace.as_posix() + "/storefront/lib/cart.ts")
    (admin, _), (storefront, hidden) = seen  # suite order
    assert storefront.name == "storefront" and admin.name == "admin"
    for cwd, folders in seen:
        assert suite in folders  # the answers, and a fetched suite's repos
        assert not any(cwd.is_relative_to(f) for f in folders)  # its own repo stays readable
    assert whole == [True, True]
    assert admin.parent.parent in hidden  # storefront's session can't read admin's copy


def test_sessions_are_denied_their_hidden_folders() -> None:
    from cairn.bench.runner import ClaudeRunner, deny_rule

    assert deny_rule(Path("C:/Temp/cairn-bench-x")) == "Read(//c/Temp/cairn-bench-x/**)"
    assert deny_rule(Path("/tmp/cairn-bench-x")).endswith("/tmp/cairn-bench-x/**)")
    assert deny_rule(Path("/tmp/cairn-bench-x")).startswith("Read(//")
    settings = ClaudeRunner().isolation_settings(Path("/tmp/ws"), (Path("/tmp/run"),))
    assert settings["permissions"] == {"deny": [deny_rule(Path("/tmp/run"))]}
    assert "permissions" not in ClaudeRunner().isolation_settings(Path("/tmp/ws"))
    command = ClaudeRunner().command("p", Path("/tmp/ws"), None, (Path("/tmp/run"),))
    assert "Read(//" in command[command.index("--settings") + 1]
    # Read, Grep and Glob work inside the workspace without a rule; by name they'd read any path
    assert command[command.index("--allowedTools") + 1 : command.index("--add-dir")] == [
        "mcp__cairn"
    ]


def test_condition_c_keeps_the_org_section_of_the_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "cairn.bench.conditions.org_index_lines", lambda ws, workspace, config: ["ORG LINE"]
    )
    seen: list[str] = []

    def reply(prompt: str, cwd: Path) -> str:
        seen.append((cwd.parent / "CLAUDE.md").read_text(encoding="utf-8"))
        return reply_json("lib/cart.ts")

    run_bench(
        suite_with_org(tmp_path),
        conditions=("C",),
        runs=1,
        task_ids=("cart-total",),
        runner=FakeRunner(reply),
        out_dir=tmp_path / "out",
        now="x",
        scope="repo",
        org_setup=no_drift,
    )
    assert "ORG LINE" in seen[0]


def test_codex_cant_run_repo_scope(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app, ["bench", str(suite_with_org(tmp_path)), "--scope", "repo", "--harness", "codex"]
    )
    assert result.exit_code == 1 and "needs claude" in result.output


def test_drift_goes_in_the_header(tmp_path: Path) -> None:
    def drifted(cache_ws: Path, org: OrgSource, tasks: Sequence[Task]) -> dict[str, list[str]]:
        return {"refund-logic": ["orders-svc/app/refunds.py"]}

    out = tmp_path / "out"
    run_bench(
        suite_with_org(tmp_path),
        conditions=("A",),
        runs=1,
        task_ids=("refund-logic",),
        runner=FakeRunner(lambda prompt, cwd: reply_json("no idea")),
        out_dir=out,
        now="x",
        scope="repo",
        org_setup=drifted,
    )
    header = json.loads((out / "x.jsonl").read_text(encoding="utf-8").split("\n")[0])["_header"]
    assert "refund-logic: orders-svc/app/refunds.py" in header["org_drift"]


def test_repo_scope_needs_an_org(tmp_path: Path) -> None:
    suite = suite_with_org(tmp_path, org=None)
    with pytest.raises(CairnError, match="names no org"):
        run_bench(
            suite,
            conditions=("A",),
            runs=1,
            task_ids=None,
            runner=FakeRunner(lambda prompt, cwd: reply_json("")),
            out_dir=tmp_path / "out",
            now="x",
            scope="repo",
        )
    result = CliRunner().invoke(app, ["bench", str(suite), "--scope", "repo"])
    assert result.exit_code == 1 and "names no org" in result.output
    result = CliRunner().invoke(app, ["bench", str(suite), "--scope", "org"])
    assert result.exit_code == 1 and "unknown scope" in result.output


def test_a_log_resumes_only_in_its_own_scope(tmp_path: Path) -> None:
    log = tmp_path / "old.jsonl"
    log.write_text(json.dumps({"_header": {"suite": "shopverse", "runs": 1}}) + "\n")
    with pytest.raises(CairnError, match="scope 'workspace'"):
        run_bench(
            suite_with_org(tmp_path),
            conditions=("A",),
            runs=1,
            task_ids=None,
            runner=FakeRunner(lambda prompt, cwd: reply_json("")),
            out_dir=tmp_path / "out",
            now="x",
            resume=log,
            scope="repo",
            org_setup=no_drift,
        )


def test_regrade_reads_org_paths_through_the_org_the_run_used(tmp_path: Path) -> None:
    out = tmp_path / "out"
    suite = suite_with_org(tmp_path)
    run_bench(
        suite,
        conditions=("A",),
        runs=1,
        task_ids=("refund-logic",),
        runner=FakeRunner(lambda prompt, cwd: reply_json("shopverse/orders-svc/app/refunds.py")),
        out_dir=out,
        now="x",
        scope="repo",
        org_setup=no_drift,
    )
    header = json.loads((out / "x.jsonl").read_text(encoding="utf-8").split("\n")[0])
    assert header["_header"]["org"]["org"] == "shopverse"
    renamed = suite_with_org(tmp_path / "later", org="someone-else")  # suite.yaml changed since
    ws = materialize(suite / load_suite(suite).workspace, tmp_path / "fresh")
    (record,) = regrade_log(out / "x.jsonl", renamed, ws)
    assert record.grade.success


@pytest.fixture
def org_ws(tmp_path: Path) -> Path:
    """Three repos of org `shopverse`; faas-netes has a folder named like the org."""
    for path in (
        "orders-svc/app/refunds.py",
        "templates/x.yaml",
        "faas-netes/chart/shopverse/templates/d.yaml",
    ):
        file = tmp_path / "ws" / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("x", encoding="utf-8")
    return tmp_path / "ws"


ORG_REPOS = {"orders-svc", "templates", "faas-netes"}


@pytest.mark.parametrize(
    ("written", "path"),
    [
        ("shopverse/orders-svc/app/refunds.py", "orders-svc/app/refunds.py"),
        ("github.com/shopverse/orders-svc/app/refunds.py", "orders-svc/app/refunds.py"),
        ("ShopVerse/Orders-Svc/app/refunds.py:12", "orders-svc/app/refunds.py:12"),
        (
            "https://github.com/shopverse/orders-svc/blob/main/app/refunds.py#L3",
            "orders-svc/app/refunds.py#L3",
        ),
        (
            "https://github.com/shopverse/orders-svc/blob/feature/x/app/refunds.py",
            "orders-svc/app/refunds.py",
        ),
        (
            "https://raw.githubusercontent.com/shopverse/orders-svc/main/app/refunds.py",
            "orders-svc/app/refunds.py",
        ),
        ("shopverse/unknown-repo/x.py", "shopverse/unknown-repo/x.py"),  # no such repo
        ("shopverse/orders-svc/gone.py", "shopverse/orders-svc/gone.py"),  # no such file
        ("ws/shopverse/orders-svc/x.py", "ws/shopverse/orders-svc/x.py"),  # a path, not the org
        # a folder named like the org, in another repo: its file stays its own
        ("shopverse/templates/d.yaml", "shopverse/templates/d.yaml"),
    ],
)
def test_org_paths(org_ws: Path, written: str, path: str) -> None:
    assert org_paths(written, ORG, org_ws, ORG_REPOS) == path


def test_gitlab_links_are_read_too(tmp_path: Path) -> None:
    (tmp_path / "api" / "app").mkdir(parents=True)
    (tmp_path / "api" / "app" / "x.py").write_text("x", encoding="utf-8")
    org = OrgSource(org="acme/platform", host="gitlab.com")
    link = "https://gitlab.com/acme/platform/api/-/blob/main/app/x.py"
    assert org_paths(link, org, tmp_path, {"api"}) == "api/app/x.py"


def test_run_ws_starts_a_word() -> None:
    import cairn.bench.run as run_module

    text = r"faas/x.go,C:\Users\a\cairn-bench-1\ws\faas\y.go"
    assert run_module._RUN_WS.sub(lambda _: "WS", text) == r"faas/x.go,WS\faas\y.go"


def test_grade_without_an_org_leaves_org_paths_alone(tmp_path: Path) -> None:
    ws = materialize(SUITE / "fixtures", tmp_path / "ws")
    task = next(t for t in load_suite(SUITE).tasks if t.id == "refund-logic")
    text = "shopverse/orders-svc/app/refunds.py"
    assert grade(task, text, ws, REPOS, ORG).success
    assert not grade(task, text, ws, REPOS).success


def test_prepare_org_warms_the_caches_and_finds_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(solo, "catalog_index", lambda ws, org: calls.append("catalog"))
    monkeypatch.setattr(solo, "packages_text", lambda ws, org: calls.append("packages"))
    monkeypatch.setattr(solo, "profile_text", lambda ws, org: calls.append("profile"))

    class Client:
        def file_exists(self, repo: str, path: str) -> bool:
            calls.append(f"{repo}/{path}")
            if path == "app/moved.py":
                raise CairnError("shopverse/orders-svc has moved")
            return path != "app/gone.py"

    monkeypatch.setattr(solo, "with_client", lambda org, call: call(Client()))
    task = Task(
        id="t",
        category="impact",
        repo="admin",
        prompt="p",
        expect_files=(
            "admin/lib/db.ts",
            "orders-svc/app/main.py",
            "orders-svc/app/gone.py",
            "orders-svc/app/moved.py",
        ),
    )
    drift = solo.prepare_org(tmp_path / "cache", ORG, [task])
    assert drift == {
        "t": [
            "orders-svc/app/gone.py",
            "orders-svc/app/moved.py (unchecked: shopverse/orders-svc has moved)",
        ]
    }
    assert calls == [
        "catalog",
        "packages",
        "profile",
        "shopverse/orders-svc/app/main.py",  # the task's own repo is on disk: never read
        "shopverse/orders-svc/app/gone.py",
        "shopverse/orders-svc/app/moved.py",
    ]
    assert "org: shopverse" in config_file(tmp_path / "cache").read_text(encoding="utf-8")


def test_a_solo_workspace_holds_one_repo_its_note_and_the_org_caches(tmp_path: Path) -> None:
    ws = materialize(SUITE / "fixtures", tmp_path / "ws")
    cache = tmp_path / "cache"
    (cache / ".cairn" / "cache" / "orgs" / "github.com").mkdir(parents=True)
    (cache / ".cairn" / "cache" / "orgs" / "github.com" / "shopverse.catalog.json").write_text("{}")
    made, home = solo.solo_workspace(ws, "admin", tmp_path / "run", ORG, cache)
    assert {p.name for p in made.iterdir()} == {"admin", ".cairn"}
    assert (made / "admin" / ".git").is_dir() and home == tmp_path / "run"
    assert (made / ".cairn" / "cache" / "orgs" / "github.com" / "shopverse.catalog.json").is_file()
    assert sorted(p.name for p in (made / ".cairn" / "authored").iterdir()) == ["admin.yaml"]
    assert yaml.safe_load(config_file(made).read_text(encoding="utf-8")) == {
        "orgs": [{"org": "shopverse"}]
    }


def test_drift_note() -> None:
    assert solo.drift_note({}) == ""
    note = solo.drift_note({"b": ["r/x"], "a": ["r/y", "r/z"]})
    assert note.endswith("a: r/y, r/z; b: r/x.")
