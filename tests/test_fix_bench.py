"""Final-review fixes: benchmark validity and safety (Phase 2c)."""

import json
import re
from pathlib import Path

import pytest

import cairn
from cairn.bench import runner as runner_module
from cairn.bench.conditions import prepare
from cairn.bench.grading import Grade, mentioned_files
from cairn.bench.report import render_markdown
from cairn.bench.run import RunRecord, run_bench
from cairn.bench.runner import (
    ClaudeRunner,
    FakeRunner,
    RunResult,
    forget_project,
    parse_result,
    project_slug,
)
from cairn.bench.suite import load_suite

SUITE = Path(__file__).resolve().parents[1] / "bench" / "suites" / "shopverse"
IDS = {"storefront", "orders-svc", "shared-types", "admin"}


@pytest.fixture(autouse=True)
def _homes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAIRN_HOME", str(tmp_path / "ch"))
    monkeypatch.setenv("CAIRN_USER_HOME", str(tmp_path / "uh"))


def test_cwd_relative_dotted_and_bracketed_paths(tmp_path: Path) -> None:
    # Final review I3
    ws = tmp_path / "ws"
    text = (
        "See ./lib/cart.ts, ../orders-svc/app/refunds.py and app/orders/[id]/page.tsx; "
        "ignore ../../etc/passwd."
    )
    assert mentioned_files(text, ws, "storefront", IDS) == {
        "storefront/lib/cart.ts",
        "orders-svc/app/refunds.py",
        "storefront/app/orders/[id]/page.tsx",
    }


def test_absolute_paths_match_any_spelling_of_the_root(tmp_path: Path) -> None:
    # Final review I3: symlinked/short/MSYS spellings of the same workspace.
    real = tmp_path / "ws"
    (real / "orders-svc" / "app").mkdir(parents=True)
    (real / "orders-svc" / "app" / "main.py").write_text("", encoding="utf-8")
    roundabout = tmp_path / "ws" / ".." / "ws"
    cited = [f"{real.resolve().as_posix()}/orders-svc/app/main.py"]
    drive = re.match(r"([A-Za-z]):/(.*)", real.resolve().as_posix())
    if drive:  # Git Bash prints C:/x as /c/x
        cited.append(f"/{drive.group(1).lower()}/{drive.group(2)}/orders-svc/app/main.py")
    for path in cited:
        found = mentioned_files(f"edit {path}", roundabout, "storefront", IDS)
        assert found == {"orders-svc/app/main.py"}, path


def test_condition_c_is_index_only(tmp_path: Path) -> None:
    # Final review I4: no dangling card pointer, no graph JSON to read instead.
    ws = prepare("C", load_suite(SUITE), SUITE, tmp_path / "C").ws
    text = (ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert "orders-svc" in text and ".cairn/cards" not in text and "card first" not in text
    cairn_dir = ws / ".cairn"
    assert not (cairn_dir / "cards").exists()
    assert not (cairn_dir / "workspace.json").exists()
    assert not (cairn_dir / "authored").exists()
    d_text = (prepare("D", load_suite(SUITE), SUITE, tmp_path / "D").ws / "CLAUDE.md").read_text(
        encoding="utf-8"
    )
    assert ".cairn/cards/" in d_text


def test_runner_allows_no_shell_and_launches_the_resolved_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Final review I5 (find -exec/-delete) and M8 (npm's claude.cmd on Windows)
    shim = str(tmp_path / "claude.cmd")
    monkeypatch.setattr(runner_module.shutil, "which", lambda name: shim)
    cmd = ClaudeRunner().command("q?", tmp_path, None)
    assert cmd[0] == shim
    assert not any(part.startswith("Bash") for part in cmd)


def test_project_dir_left_by_a_run_is_removed_only_when_empty(tmp_path: Path) -> None:
    # Final review I6: headless runs leave ~/.claude/projects/<slug>/memory behind.
    cwd = Path("C:/Users/x/AppData/Local/Temp/cairn-bench-ab_cd/ws/storefront")
    slug = project_slug(cwd)
    assert slug == "C--Users-x-AppData-Local-Temp-cairn-bench-ab-cd-ws-storefront"
    home = tmp_path / "claude"
    (home / "projects" / slug / "memory").mkdir(parents=True)
    forget_project(home, cwd)
    assert not (home / "projects" / slug).exists()
    (home / "projects" / slug / "memory").mkdir(parents=True)
    (home / "projects" / slug / "memory" / "note.md").write_text("x", encoding="utf-8")
    forget_project(home, cwd)
    assert (home / "projects" / slug / "memory" / "note.md").exists()


def _reply(prompt: str, cwd: Path) -> str:
    return json.dumps(
        {
            "result": "storefront/lib/cart.ts",
            "num_turns": 2,
            "total_cost_usd": 0.02,
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "modelUsage": {"claude-haiku-4-5-20251001": {"inputTokens": 1}},
        }
    )


def test_results_record_versions_and_models(tmp_path: Path) -> None:
    # Final review I9 (spec §11 Rigor)
    run_bench(
        SUITE,
        conditions=("A",),
        runs=1,
        task_ids=("cart-total",),
        runner=FakeRunner(_reply),
        out_dir=tmp_path,
        now="s",
        meta={"model": "haiku", "claude_version": "2.1.0 (Claude Code)"},
    )
    data = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
    meta = data["meta"]
    assert meta["cairn_version"] == cairn.__version__ and meta["suite"] == "shopverse"
    assert meta["model"] == "haiku" and meta["claude_version"].startswith("2.1.0")
    assert meta["conditions"] == ["A"] and meta["runs"] == 1
    assert data["records"][0]["result"]["models"] == ["claude-haiku-4-5-20251001"]


def test_each_run_is_saved_as_it_finishes(tmp_path: Path) -> None:
    # Final review M7 (re-graded): a crash must not lose the paid runs before it.
    calls = []

    def flaky(prompt: str, cwd: Path) -> str:
        calls.append(prompt)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return _reply(prompt, cwd)

    with pytest.raises(KeyboardInterrupt):
        run_bench(
            SUITE,
            conditions=("A",),
            runs=2,
            task_ids=("cart-total",),
            runner=FakeRunner(flaky),
            out_dir=tmp_path,
            now="s",
        )
    lines = (tmp_path / "s.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["task_id"] == "cart-total"


def test_errored_runs_are_counted_but_not_averaged() -> None:
    # Final review M10 (re-graded)
    ok = RunResult(result_text="x", cost_usd=0.05, num_turns=4, output_tokens=100)
    failed = parse_result("Error: rate limited")
    records = [
        RunRecord("A", "t", 0, Grade(True, 1.0, 1.0), ok),
        RunRecord("A", "t", 1, Grade(False, 0.0, 0.0), failed),
    ]
    summary = next(
        line for line in render_markdown(records).splitlines() if line.startswith("| A |")
    )
    cells = [c.strip() for c in summary.strip("|").split("|")]
    assert cells[1] == "2"  # runs
    assert "0.0500" in cells and "4.0" in cells  # means over the successful run only
    assert cells[-1] == "1"  # errors column


def test_scan_summary_line_is_plain_ascii(tmp_path: Path) -> None:
    # Final review M12: cp1252 consoles print '?' for a middot.
    from typer.testing import CliRunner

    from cairn.cli import app
    from tests.helpers import make_repo

    make_repo(tmp_path, "alpha")
    output = CliRunner().invoke(app, ["scan", str(tmp_path)]).output
    assert "from cache" in output and output.isascii()


def test_runs_never_load_the_users_own_claude_md_or_rules(tmp_path: Path) -> None:
    # Probe (claude 2.1.289): --setting-sources project,local still loaded ~/.claude/rules/*.md.
    ws = tmp_path / "run" / "ws"
    home = tmp_path / "claude-home"
    cmd = ClaudeRunner(home=home).command("q?", ws, None)
    settings = json.loads(cmd[cmd.index("--settings") + 1])
    excludes = settings["claudeMdExcludes"]
    assert f"{home.as_posix()}/**" in excludes
    for ancestor in ws.parents:
        assert f"{ancestor.as_posix().rstrip('/')}/CLAUDE.md" in excludes
    assert f"{ws.as_posix()}/CLAUDE.md" not in excludes  # the condition's own context
    assert settings["autoMemoryEnabled"] is False
