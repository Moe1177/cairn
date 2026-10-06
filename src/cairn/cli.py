"""cairn command-line interface."""

import os
import shutil
import sys
import tempfile
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from cairn import deep as deep_ops
from cairn import providers
from cairn.authored_store import annotate_edge, set_summary
from cairn.emit import write_outputs
from cairn.errors import CairnError
from cairn.integrations.claude import install_claude, is_installed, sync_claude
from cairn.integrations.git_hooks import install_hooks, uninstall_hooks
from cairn.integrations.harnesses import (
    HARNESSES,
    install_harness,
    installed_harnesses,
    uninstall_harness,
)
from cairn.load import load_authored
from cairn.model.graph import Confidence, Repo, Workspace
from cairn.paths import cairn_dir
from cairn.providers.meta import indexed_repos
from cairn.scan import ScanResult, scan_workspace
from cairn.scan_log import render_log
from cairn.store.lock import workspace_lock
from cairn.store.workspace_store import load_workspace

app = typer.Typer(
    no_args_is_help=True,
    add_completion=True,
    pretty_exceptions_enable=False,
    help="cairn: a workspace map for coding agents.",
)
PathArg = Annotated[Path, typer.Argument(help="Workspace root (default: current directory).")]


def _version(value: bool) -> None:
    if not value:
        return
    import platform
    from importlib.metadata import PackageNotFoundError, version

    import cairn

    try:
        mcp_version = version("mcp")
    except PackageNotFoundError:
        mcp_version = "not installed"
    typer.echo(f"cairn {cairn.__version__}")
    typer.echo(f"Python {platform.python_version()} on {platform.platform()}, mcp {mcp_version}")
    raise typer.Exit()


@app.callback()
def _main(
    _version_flag: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version,
            is_eager=True,
            help="Show cairn, Python, platform and mcp versions, then exit.",
        ),
    ] = False,
) -> None:
    """cairn: a workspace map for coding agents."""
    # Legacy consoles (e.g. Windows cp1252) cannot encode every character in
    # paths or messages; print a replacement character instead of crashing.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            # Piped output is read by agents and scripts that expect UTF-8, not the console
            # code page; a terminal keeps its own encoding but never crashes on a character.
            piped = not stream.isatty()
            reconfigure(**({"encoding": "utf-8"} if piped else {}), errors="replace")


def _fail(message: str) -> NoReturn:
    typer.echo(f"error: {message}", err=True)
    raise typer.Exit(1)


def _harness_names(harness: str) -> tuple[str, ...]:
    if harness == "all":
        return HARNESSES
    if harness not in HARNESSES:
        _fail(f"unknown harness '{harness}' (choose from: {', '.join(HARNESSES)}, all).")
    return (harness,)


def _run_for(names: tuple[str, ...], action: Callable[[str], tuple[str, ...]]) -> None:
    """Run per harness; one broken harness config doesn't stop the others."""
    failed = False
    for name in names:
        try:
            for line in action(name):
                typer.echo(line)
        except (CairnError, OSError) as exc:  # e.g. a config file locked by the running app
            failed = True
            typer.echo(f"{name}: error: {exc}", err=True)
    if failed:
        raise typer.Exit(1)


def _scan_and_write(path: Path, *, use_cache: bool = True) -> ScanResult:
    root = path.resolve()
    first: ScanResult | None = None
    if not cairn_dir(root).exists():
        # First scan here: don't create .cairn/ in a folder that has no repos.
        first = scan_workspace(root, use_cache=use_cache)
        if not first.workspace.repos:
            return first
    with workspace_lock(root):
        result = first or scan_workspace(root, use_cache=use_cache)
        write_outputs(root, result)
        sync_claude(root)
        return result


def _summary_line(result: ScanResult) -> str:
    workspace = result.workspace
    counts = Counter(e.confidence.value for e in workspace.edges)
    detail = ", ".join(f"{counts[c.value]} {c.value}" for c in Confidence if counts[c.value])
    suffix = f" ({detail})" if detail else ""
    return (
        f"Mapped {len(workspace.repos)} repos and {len(workspace.edges)} relationships{suffix} "
        f"-> .cairn/INDEX.md; {len(result.cached)} from cache"
    )


def _report(result: ScanResult, *, verbose: bool = False) -> None:
    if not result.workspace.repos:
        root = result.workspace.workspace_root
        existing = cairn_dir(Path(root)).exists()
        tail = "the map is now empty." if existing else "nothing written."
        typer.echo(f"No git repos found under {root}; {tail}")
        return
    typer.echo(_summary_line(result))
    for warning in result.warnings:
        typer.echo(f"warning: {warning}", err=True)
    if verbose:
        typer.echo(render_log(result), err=True)


Verbose = Annotated[bool, typer.Option("--verbose", help="Print the scan log to stderr.")]


@app.command()
def scan(
    path: PathArg = Path("."),
    full: Annotated[
        bool, typer.Option("--full", help="Ignore the cache; re-read every repo.")
    ] = False,
    verbose: Verbose = False,
) -> None:
    """Map every git repo under PATH into .cairn/."""
    try:
        result = _scan_and_write(path, use_cache=not full)
    except (CairnError, OSError, ValidationError) as exc:
        _fail(str(exc))
    _report(result, verbose=verbose)


@app.command()
def refresh(
    path: PathArg = Path("."),
    quiet: Annotated[bool, typer.Option("--quiet", help="Print nothing unless it fails.")] = False,
    verbose: Verbose = False,
    deep: Annotated[
        bool | None,
        typer.Option(
            "--deep/--no-deep",
            help="Rebuild stale deep indexes (default: when any exist and graphify is installed).",
        ),
    ] = None,
) -> None:
    """Update the map, re-reading only repos that changed since the last scan."""
    try:
        result = _scan_and_write(path)
    except (CairnError, OSError) as exc:
        _fail(str(exc))
    if not quiet:
        _report(result, verbose=verbose)
    root = path.resolve()
    if deep is None:  # by default only when deep indexes exist and graphify can rebuild them
        deep = bool(indexed_repos(root)) and providers.default_provider().available()
    if deep and result.workspace.repos:
        _build_deep(
            root,
            lambda: deep_ops.select_repos(
                root, result.workspace, [], every=False, stale=True, skip_failed=True
            ),
            timeout=deep_ops.DEFAULT_TIMEOUT,
            quiet=quiet,
        )


@app.command()
def init(
    path: PathArg = Path("."),
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Install the Claude Code integration without asking."),
    ] = False,
    no_install: Annotated[bool, typer.Option("--no-install", help="Only scan.")] = False,
) -> None:
    """Scan PATH and offer to load the index into Claude Code."""
    try:
        result = _scan_and_write(path)
        _report(result)
        if not result.workspace.repos:
            typer.echo(
                f"No git repos found under {path.resolve()}. "
                "Run `cairn init` from the folder that contains your repos."
            )
            return
        if no_install:
            typer.echo("Run `cairn install claude` to load the index into Claude Code.")
            return
        prompt = (
            "Add the repo index to CLAUDE.md in this folder so Claude Code loads it automatically?"
        )
        if yes or typer.confirm(prompt, default=True):
            typer.echo(f"Claude Code: index added to {install_claude(path.resolve())}")
        else:
            typer.echo("Skipped. Run `cairn install claude` any time.")
    except (CairnError, OSError) as exc:
        _fail(str(exc))


@app.command()
def install(
    harness: str,
    path: PathArg = Path("."),
    per_repo: Annotated[
        bool, typer.Option("--per-repo", help="Cursor: also add a git-excluded rule to each repo.")
    ] = False,
) -> None:
    """Load cairn into a harness: claude, codex, gemini, cursor, or all."""
    root = path.resolve()
    _run_for(_harness_names(harness), lambda name: install_harness(name, root, per_repo=per_repo))


@app.command()
def uninstall(harness: str, path: PathArg = Path(".")) -> None:
    """Remove cairn from a harness: claude, codex, gemini, cursor, or all."""
    root = path.resolve()
    _run_for(_harness_names(harness), lambda name: uninstall_harness(name, root))


@app.command()
def status(path: PathArg = Path(".")) -> None:
    """Show what cairn knows about PATH."""
    root = path.resolve()
    try:
        workspace = load_workspace(root)
        authored = load_authored(root)
    except (CairnError, OSError) as exc:
        _fail(str(exc))
    if workspace is None:
        _fail("No map found. Run `cairn scan` first.")
    counts = Counter(e.confidence.value for e in workspace.edges)
    missing = [r.id for r in workspace.repos if not (r.id in authored and authored[r.id].summary)]
    stale = [r.id for r in workspace.repos if r.summary_stale]
    errors = [
        f"{r.id}: {e.detector}: {e.message}" for r in workspace.repos for e in r.detector_errors
    ]
    lines = [
        f"Workspace: {workspace.workspace_root}",
        f"Generated: {workspace.generated_at}",
        f"Repos: {len(workspace.repos)}",
        f"Edges: {len(workspace.edges)} "
        f"({', '.join(f'{counts[c.value]} {c.value}' for c in Confidence)})",
        f"Repos without an authored summary: {', '.join(missing) or 'none'}",
        f"Possibly stale summaries: {', '.join(stale) or 'none'}",
        f"Detector errors: {'; '.join(errors) or 'none'}",
        f"Claude Code integration: {'installed' if is_installed(root) else 'not installed'}",
        f"Harnesses: {', '.join(installed_harnesses(root)) or 'none'}",
        f"Deep indexes: {', '.join(indexed_repos(root)) or 'none'}",
    ]
    weak = [e for e in workspace.edges if e.confidence is Confidence.AMBIGUOUS]
    if weak:
        lines.append(f"Unconfirmed links ({len(weak)}):")
        lines += [f"  {e.key}  [{', '.join(e.signals[:3])}]" for e in weak]
        lines.append(
            "Confirm or reject with: cairn annotate-edge <key> --confirm|--reject [--why TEXT]"
        )
    typer.echo("\n".join(lines))


@app.command()
def doctor(path: PathArg = Path(".")) -> None:
    """Check git, Python, the map, write access, harnesses and graphify; say what to fix."""
    from cairn.doctor import FAIL, run_checks

    checks = run_checks(path.resolve())
    typer.echo("\n".join(check.line() for check in checks))
    if any(check.status == FAIL for check in checks):
        raise typer.Exit(1)


@app.command("annotate-edge")
def annotate_edge_cmd(
    key: str,
    path: PathArg = Path("."),
    confirm: Annotated[bool, typer.Option("--confirm", help="Mark the link as real.")] = False,
    reject: Annotated[bool, typer.Option("--reject", help="Mark the link as wrong.")] = False,
    why: Annotated[
        str | None, typer.Option("--why", help="One-line reason shown on cards.")
    ] = None,
) -> None:
    """Confirm, reject, or explain a relationship, then re-scan."""
    if (confirm and reject) or not (confirm or reject or why):
        _fail("pass --confirm, --reject, or --why (and not both --confirm and --reject).")
    review = "confirmed" if confirm else "rejected" if reject else None
    try:
        written = annotate_edge(path.resolve(), key, review=review, why=why)
        typer.echo(f"Saved to {written}")
        _report(_scan_and_write(path))
    except (CairnError, OSError) as exc:
        _fail(str(exc))


def serve_start(workspace: Path | None, from_dir: Path | None) -> tuple[Path | None, Path]:
    """(workspace root or None, folder the search started from) for `cairn serve`."""
    from cairn.mcp_server.server import find_workspace

    start = from_dir or Path.cwd()
    if workspace:
        return workspace.resolve(), start
    return (find_workspace(start) if start.is_dir() else None), start


@app.command()
def serve(
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace", help="Workspace root (default: found from the current directory)."
        ),
    ] = None,
    from_dir: Annotated[
        Path | None,
        typer.Option(
            "--from",
            help="Find the workspace from this folder instead of the current directory "
            "(editors that start servers elsewhere pass the open folder).",
        ),
    ] = None,
) -> None:
    """Run the cairn MCP server over stdio (harnesses start this for you)."""
    from cairn.mcp_server.server import build_server

    root, start = serve_start(workspace, from_dir)
    # Outside a workspace the server still starts and its tools explain how to set one up,
    # so a globally registered cairn never shows as a failed server in unrelated projects.
    build_server(root, start=start).run()


@app.command("set-summary")
def set_summary_cmd(
    repo: str,
    summary: str,
    path: PathArg = Path("."),
    alias: Annotated[
        list[str] | None, typer.Option("--alias", help="Another name people use (repeatable).")
    ] = None,
) -> None:
    """Save a one-or-two sentence summary for a repo (use - to read stdin), then re-scan."""
    text = sys.stdin.buffer.read().decode("utf-8-sig", "replace") if summary == "-" else summary
    try:
        written = set_summary(path.resolve(), repo, text, aliases=alias or ())
        typer.echo(f"Saved to {written}")
        _report(_scan_and_write(path))
    except (CairnError, OSError) as exc:
        _fail(str(exc))


def _comma_list(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


@contextmanager
def _isolated_cairn_homes() -> Iterator[None]:
    """Benchmarks never read or write the user's real cairn/harness homes."""
    names = ("CAIRN_HOME", "CAIRN_USER_HOME")
    saved = {name: os.environ.get(name) for name in names}
    with tempfile.TemporaryDirectory(prefix="cairn-bench-home-") as tmp:
        for name in names:
            os.environ[name] = str(Path(tmp) / name.lower())
        try:
            yield
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


@app.command()
def bench(
    suite_dir: Annotated[Path, typer.Argument(help="Benchmark suite folder (has suite.yaml).")],
    conditions: Annotated[
        str, typer.Option("--conditions", help="Comma list of A,B,C,D,E.")
    ] = "A,B,C,D,E",
    runs: Annotated[int, typer.Option("--runs", min=1, help="Runs per condition × task.")] = 1,
    tasks: Annotated[
        str | None, typer.Option("--tasks", help="Comma list of task ids (default: all).")
    ] = None,
    model: Annotated[str, typer.Option("--model", help="Claude model for the agent.")] = "haiku",
    out: Annotated[Path, typer.Option("--out", help="Folder for the reports.")] = Path(
        "bench/results"
    ),
    resume: Annotated[
        Path | None,
        typer.Option("--resume", help="Continue a run's .jsonl log: only missing/failed runs."),
    ] = None,
) -> None:
    """Measure what cairn saves: run a suite headlessly in Claude Code under each condition."""
    from cairn.bench.conditions import CONDITIONS
    from cairn.bench.run import run_bench
    from cairn.bench.runner import ClaudeRunner
    from cairn.bench.suite import load_suite

    chosen = _comma_list(conditions)
    unknown = [c for c in chosen if c not in CONDITIONS]
    if unknown or not chosen:
        _fail(f"unknown condition {', '.join(unknown) or '(none)'} (choose from A,B,C,D,E).")
    try:
        suite = load_suite(suite_dir)
    except (CairnError, OSError) as exc:
        _fail(str(exc))
    task_ids = _comma_list(tasks) if tasks else None
    missing = [t for t in task_ids or () if t not in {task.id for task in suite.tasks}]
    if missing:
        _fail(f"unknown task {', '.join(missing)} in suite {suite.name}.")
    if shutil.which("claude") is None:
        _fail("the `claude` CLI is not on PATH; install Claude Code to run benchmarks.")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    runner = ClaudeRunner(model=model)
    meta = {"model": model, "claude_version": runner.version()}
    if resume is not None and not resume.is_file():
        _fail(f"no run log at {resume}.")
    try:
        with _isolated_cairn_homes():
            records = run_bench(
                suite_dir.resolve(),
                conditions=chosen,
                runs=runs,
                task_ids=task_ids,
                runner=runner,
                out_dir=out,
                now=stamp,
                meta=meta,
                resume=resume,
            )
    except CairnError as exc:  # BenchStopped (a usage limit) or a suite that can't be fetched
        _fail(str(exc))
    from cairn.bench.report import render_markdown

    stem = resume.with_suffix("") if resume else out / stamp
    typer.echo(render_markdown(records, meta=meta))
    typer.echo(f"Reports: {stem}.md and {stem}.json")


@app.command()
def hooks(action: str, path: PathArg = Path(".")) -> None:
    """Git hooks that refresh the map after commits and merges: install | uninstall."""
    if action not in ("install", "uninstall"):
        _fail("use `cairn hooks install` or `cairn hooks uninstall`.")
    try:
        report = (install_hooks if action == "install" else uninstall_hooks)(path.resolve())
    except (CairnError, OSError) as exc:
        _fail(str(exc))
    count = len(report.changed)
    typer.echo(f"git hooks {action}ed in {count} repo{'' if count == 1 else 's'}")
    for repo, why in report.skipped:
        typer.echo(f"skipped {repo}: {why}")


deep_app = typer.Typer(
    no_args_is_help=True, help="Per-repo code indexes for `query` (graphify; optional)."
)
app.add_typer(deep_app, name="deep")
Repos = Annotated[list[str] | None, typer.Argument(help="Repo names (ids or aliases).")]
WorkspaceOpt = Annotated[
    Path, typer.Option("--workspace", "-w", help="Workspace root (default: current directory).")
]


def _loaded(root: Path) -> Workspace:
    try:
        workspace = load_workspace(root)
    except (CairnError, OSError) as exc:
        _fail(str(exc))
    if workspace is None:
        _fail("No map found. Run `cairn scan` first.")
    return workspace


def _build_deep(
    root: Path,
    pick: Callable[[], list[Repo]],
    *,
    timeout: float,
    quiet: bool = False,
    none_message: str | None = None,
) -> None:
    """Build the picked indexes, print one line each, then re-scan so cards show them.

    The re-scan comes after the build: a build can take minutes, and writing a scan taken
    before it would undo whatever a hook or an MCP refresh mapped in the meantime.
    """
    try:
        picked = pick()
        outcomes = deep_ops.build(root, picked, timeout=timeout)
    except (CairnError, OSError) as exc:
        _fail(str(exc))
    if not picked and none_message and not quiet:
        typer.echo(none_message)
    for outcome in outcomes:
        if not (quiet and outcome.ok):
            typer.echo(outcome.message, err=not outcome.ok)
    if outcomes:
        try:
            _scan_and_write(root)
        except (CairnError, OSError) as exc:
            _fail(str(exc))
    if not all(o.ok for o in outcomes):
        raise typer.Exit(1)


@deep_app.command("enable")
def deep_enable(
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Install without asking.")] = False,
    timeout: Annotated[
        float, typer.Option("--timeout", min=1, help="Seconds allowed per repo.")
    ] = deep_ops.DEFAULT_TIMEOUT,
    workspace: WorkspaceOpt = Path("."),
) -> None:
    """Turn deep queries on: install graphify if needed, then index every repo."""
    root = workspace.resolve()
    loaded = _loaded(root)
    if not providers.default_provider().available():
        command = deep_ops.graphify_install_command()
        shown = " ".join(f'"{c}"' if " " in c or "<" in c or ">" in c else c for c in command)
        typer.echo(f"graphify isn't installed. Install it with: {shown}")
        if not (yes or typer.confirm("Run that now?", default=True)):
            raise typer.Exit(1)
        if deep_ops.run_installer(command) != 0:
            _fail(f"the install failed; run it yourself: {shown}")
        if not providers.default_provider().available():
            _fail("graphify installed but isn't on PATH yet: open a new terminal and rerun this.")
    _build_deep(
        root,
        lambda: deep_ops.select_repos(root, loaded, [], every=True, stale=False),
        timeout=timeout,
    )


@deep_app.command("build")
def deep_build(
    repos: Repos = None,
    every: Annotated[bool, typer.Option("--all", help="Every repo in the map.")] = False,
    stale: Annotated[
        bool, typer.Option("--stale", help="Only existing indexes that went stale.")
    ] = False,
    timeout: Annotated[
        float, typer.Option("--timeout", min=1, help="Seconds allowed per repo.")
    ] = deep_ops.DEFAULT_TIMEOUT,
    workspace: WorkspaceOpt = Path("."),
) -> None:
    """Index repos with graphify (code-only: no LLM, no network) so `query` gives file:line."""
    root = workspace.resolve()
    loaded = _loaded(root)
    _build_deep(
        root,
        lambda: deep_ops.select_repos(root, loaded, repos or [], every=every, stale=stale),
        timeout=timeout,
        none_message="No stale deep indexes." if stale else "No repos to index.",
    )


@deep_app.command("status")
def deep_status(path: PathArg = Path("."), workspace: WorkspaceOpt = Path(".")) -> None:
    """List deep indexes: size, provider version, build sha, fresh or stale."""
    # Takes the workspace as PATH (like `cairn status`) or -w (like `deep build`/`clear`).
    root = (path if path != Path(".") else workspace).resolve()
    lines = deep_ops.status_lines(root, _loaded(root))
    typer.echo("\n".join(lines) or "No deep indexes. Build one with `cairn deep build REPO`.")


@deep_app.command("clear")
def deep_clear(repos: Repos = None, workspace: WorkspaceOpt = Path(".")) -> None:
    """Delete deep indexes (all of them when no repo is named)."""
    root = workspace.resolve()
    try:
        cleared = deep_ops.clear(root, _loaded(root), repos or [])
        if cleared:
            _scan_and_write(root)
    except (CairnError, OSError) as exc:
        _fail(str(exc))
    typer.echo(f"Cleared: {', '.join(cleared)}" if cleared else "No deep indexes to clear.")


@app.command("bench-locate")
def bench_locate(
    suites: Annotated[
        list[Path], typer.Argument(help="Suite folders, each with a locate.yaml key.")
    ],
    modes: Annotated[
        str, typer.Option("--locators", help="Comma list of grep,graph,hybrid.")
    ] = "grep,graph,hybrid",
    build: Annotated[
        bool, typer.Option("--build/--no-build", help="Build missing code graphs with graphify.")
    ] = True,
    graphify: Annotated[
        str | None, typer.Option("--graphify", help="graphify executable (default: on PATH).")
    ] = None,
    cache: Annotated[
        Path, typer.Option("--cache", help="Where the materialised repos and graphs are kept.")
    ] = Path("bench/.locate-cache"),
    out: Annotated[Path, typer.Option("--out", help="Folder for the reports.")] = Path(
        "bench/results"
    ),
) -> None:
    """Offline: which locator finds the answer file, per kind of question (no agent, no cost)."""
    from cairn.bench.locate_eval import (
        evaluate,
        key_problems,
        load_locate_set,
        outcomes_json,
        prepare_locate_workspace,
        summarize,
    )
    from cairn.locate.hybrid import MODES
    from cairn.providers.graphify import GraphifyProvider

    chosen = _comma_list(modes)
    if not chosen or any(m not in MODES for m in chosen):
        _fail(f"unknown locator in {modes!r} (choose from {', '.join(MODES)}).")
    provider = GraphifyProvider(executable=graphify) if build else None
    if provider is not None and not provider.available():
        _fail("graphify isn't on PATH: pass --graphify PATH, or --no-build to use only grep.")
    outcomes = []
    try:
        for suite_dir in suites:
            locate_set = load_locate_set(suite_dir)
            ws, graphs = prepare_locate_workspace(suite_dir, cache.resolve(), provider=provider)
            problems = key_problems(ws, locate_set)
            if problems:
                _fail(f"the key of {suite_dir} doesn't match its code:\n" + "\n".join(problems))
            outcomes += evaluate(ws, graphs, locate_set, chosen)
    except (CairnError, OSError) as exc:
        _fail(str(exc))
    report = summarize(outcomes)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (out / f"locate-{stamp}.md").write_text(report, encoding="utf-8")
    (out / f"locate-{stamp}.json").write_text(outcomes_json(outcomes), encoding="utf-8")
    typer.echo(report)
