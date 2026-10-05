"""Human-readable record of the last scan (.cairn/logs/last-scan.log)."""

from cairn.scan import ScanResult


def render_log(result: ScanResult) -> str:
    workspace = result.workspace
    cached = set(result.cached)
    reread = [r.id for r in workspace.repos if r.id not in cached]
    errors = [
        f"detector error: {r.id}: {e.detector}: {e.message}"
        for r in workspace.repos
        for e in r.detector_errors
    ]
    lines = [
        f"cairn scan at {workspace.generated_at}",
        f"workspace: {workspace.workspace_root}",
        f"repos: {len(workspace.repos)} ({len(cached)} from cache, {len(reread)} re-read)",
        f"re-read: {', '.join(reread) or 'none'}",
        f"relationships: {len(workspace.edges)}",
        *errors,
        *(f"warning: {w}" for w in result.warnings),
    ]
    return "\n".join(lines) + "\n"
