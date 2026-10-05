"""cairn command-line interface."""

from collections import Counter
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from cairn.emit import write_outputs
from cairn.errors import CairnError
from cairn.integrations.claude import install_claude, is_installed, sync_claude, uninstall_claude
from cairn.load import load_authored
from cairn.model.graph import Confidence
from cairn.scan import ScanResult, scan_workspace
from cairn.store.workspace_store import load_workspace

app = typer.Typer(no_args_is_help=True, add_completion=False, help="cairn: a workspace map for coding agents.")
SUPPORTED_HARNESSES = ("claude",)
PathArg = Annotated[Path, typer.Argument(help="Workspace root (default: current directory).")]


def _fail(message: str) -> NoReturn:
    typer.echo(f"error: {message}", err=True)
    raise typer.Exit(1)


def _check_harness(harness: str) -> None:
    if harness not in SUPPORTED_HARNESSES:
        _fail(
            f"'{harness}' is not supported yet (supported: {', '.join(SUPPORTED_HARNESSES)}). "
            "Codex, Gemini CLI and Cursor arrive in the next release."
        )


def _scan_and_write(path: Path) -> ScanResult:
    root = path.resolve()
    result = scan_workspace(root)
    write_outputs(root, result)
    sync_claude(root)
    return result


def _summary_line(result: ScanResult) -> str:
    workspace = result.workspace
    counts = Counter(e.confidence.value for e in workspace.edges)
    detail = ", ".join(f"{counts[c.value]} {c.value}" for c in Confidence if counts[c.value])
    suffix = f" ({detail})" if detail else ""
    return f"Mapped {len(workspace.repos)} repos and {len(workspace.edges)} relationships{suffix} → .cairn/INDEX.md"


def _report(result: ScanResult) -> None:
    typer.echo(_summary_line(result))
    for warning in result.warnings:
        typer.echo(f"warning: {warning}", err=True)


@app.command()
def scan(path: PathArg = Path(".")) -> None:
    """Map every git repo under PATH into .cairn/."""
    try:
        result = _scan_and_write(path)
    except CairnError as exc:
        _fail(str(exc))
    _report(result)


@app.command()
def init(
    path: PathArg = Path("."),
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Install the Claude Code integration without asking.")] = False,
    no_install: Annotated[bool, typer.Option("--no-install", help="Only scan.")] = False,
) -> None:
    """Scan PATH and offer to load the index into Claude Code."""
    try:
        result = _scan_and_write(path)
        _report(result)
        if no_install:
            typer.echo("Run `cairn install claude` to load the index into Claude Code.")
            return
        prompt = "Add the repo index to CLAUDE.md in this folder so Claude Code loads it automatically?"
        if yes or typer.confirm(prompt, default=True):
            typer.echo(f"Claude Code: index added to {install_claude(path.resolve())}")
        else:
            typer.echo("Skipped. Run `cairn install claude` any time.")
    except CairnError as exc:
        _fail(str(exc))


@app.command()
def install(harness: str, path: PathArg = Path(".")) -> None:
    """Load the index into a harness (Phase 1: claude)."""
    _check_harness(harness)
    try:
        target = install_claude(path.resolve())
    except CairnError as exc:
        _fail(str(exc))
    typer.echo(f"Claude Code: index added to {target}")


@app.command()
def uninstall(harness: str, path: PathArg = Path(".")) -> None:
    """Remove cairn's block from a harness's context file."""
    _check_harness(harness)
    try:
        removed = uninstall_claude(path.resolve())
    except CairnError as exc:
        _fail(str(exc))
    typer.echo("Claude Code: cairn block removed." if removed else "Claude Code: cairn was not installed.")


@app.command()
def status(path: PathArg = Path(".")) -> None:
    """Show what cairn knows about PATH."""
    root = path.resolve()
    try:
        workspace = load_workspace(root)
        authored = load_authored(root)
    except CairnError as exc:
        _fail(str(exc))
    if workspace is None:
        _fail("No map found. Run `cairn scan` first.")
    counts = Counter(e.confidence.value for e in workspace.edges)
    missing = [r.id for r in workspace.repos if not (r.id in authored and authored[r.id].summary)]
    errors = [f"{r.id}: {e.detector}: {e.message}" for r in workspace.repos for e in r.detector_errors]
    lines = [
        f"Workspace: {workspace.workspace_root}",
        f"Generated: {workspace.generated_at}",
        f"Repos: {len(workspace.repos)}",
        f"Edges: {len(workspace.edges)} "
        f"({', '.join(f'{counts[c.value]} {c.value}' for c in Confidence)})",
        f"Repos without an authored summary: {', '.join(missing) or 'none'}",
        f"Detector errors: {'; '.join(errors) or 'none'}",
        f"Claude Code integration: {'installed' if is_installed(root) else 'not installed'}",
    ]
    typer.echo("\n".join(lines))
