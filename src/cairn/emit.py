"""Write scan results to .cairn/: workspace.json, cards, and INDEX.md."""

from pathlib import Path

from cairn.paths import cards_dir, index_file, logs_dir
from cairn.render.card import render_card
from cairn.render.index import render_index
from cairn.scan import ScanResult
from cairn.scan_log import render_log
from cairn.store.atomic import atomic_write_text
from cairn.store.workspace_store import save_workspace


def write_outputs(ws_root: Path, result: ScanResult) -> tuple[Path, ...]:
    workspace = result.workspace
    written = [save_workspace(ws_root, workspace)]
    directory = cards_dir(ws_root)
    keep: set[str] = set()
    for repo in workspace.repos:
        card = render_card(
            repo,
            workspace,
            authored=result.authored.get(repo.id),
            note=result.relations.notes.get(repo.id),
            budget=result.config.card_budget,
        )
        path = directory / f"{repo.id}.md"
        atomic_write_text(path, card)
        keep.add(path.name)
        written.append(path)
    for stale in directory.glob("*.md"):
        if stale.name not in keep:
            stale.unlink()
    index_path = index_file(ws_root)
    atomic_write_text(
        index_path,
        render_index(workspace, result.authored, threshold=result.config.index_threshold),
    )
    written.append(index_path)
    log_path = logs_dir(ws_root) / "last-scan.log"
    atomic_write_text(log_path, render_log(result))
    written.append(log_path)
    return tuple(written)
