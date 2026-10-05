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
from cairn.model.graph import Confidence
from cairn.paths import cairn_dir
from cairn.scan import ScanResult, scan_workspace
from cairn.scan_log import render_log
from cairn.store.lock import workspace_lock
from cairn.store.workspace_store import load_workspace

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
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
        typer.echo(f"No git repos found under {root}; nothing written.")
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
    except (CairnError, OSError) as exc:
        _fail(str(exc))
    _report(result, verbose=verbose)


@app.command()
def refresh(
    path: PathArg = Path("."),
    quiet: Annotated[bool, typer.Option("--quiet", help="Print nothing unless it fails.")] = False,
    verbose: Verbose = False,
) -> None:
    """Update the map, re-reading only repos that changed since the last scan."""
    try:
        result = _scan_and_write(path)
    except (CairnError, OSError) as exc:
        _fail(str(exc))
    if not quiet:
        _report(result, verbose=verbose)


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
    ]
    weak = [e for e in workspace.edges if e.confidence is Confidence.AMBIGUOUS]
    if weak:
        lines.append(f"Unconfirmed links ({len(weak)}):")
        lines += [f"  {e.key}  [{', '.join(e.signals[:3])}]" for e in weak]
        lines.append(
            "Confirm or reject with: cairn annotate-edge <key> --confirm|--reject [--why TEXT]"
        )
    typer.echo("\n".join(lines))


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
        )
    from cairn.bench.report import render_markdown

    typer.echo(render_markdown(records, meta=meta))
    typer.echo(f"Reports: {out / (stamp + '.md')} and {out / (stamp + '.json')}")


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
