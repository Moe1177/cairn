"""Text cairn installs into harnesses: the global pointer and the /cairn skill."""

import json
from collections.abc import Sequence

SKILL_DESCRIPTION = (
    "Maintain the cairn workspace map: write repo summaries and settle unconfirmed "
    "cross-repo links. Use when the user runs /cairn or `cairn status` shows work to do."
)

SKILL_BODY = """# cairn

Keep the cairn workspace map accurate. Work from the workspace root (the folder containing `.cairn/`).

0. If there is no map yet (no `.cairn/` in this folder or above it, or `cairn status` says "No map found"):
   - Find the folder that holds the user's repos: usually the parent of the current repo, the one with several git repos in it.
   - Ask the user to confirm that folder. Building the map only reads the repos; it writes `.cairn/` in that folder.
   - Run `cairn init <folder>` and report the summary line it prints, then continue from step 1 in that folder.
1. Run `cairn status`.
2. For each repo under "Repos without an authored summary" or "Possibly stale summaries":
   - Read `.cairn/cards/<repo>.md`, then the repo's README if needed (stop after ~200 lines).
   - Write one or two plain sentences: what the repo does and who or what uses it.
   - Save: `cairn set-summary <repo> "<summary>"`. Add `--alias <name>` for names people really use.
3. For each line under "Unconfirmed links":
   - Read the evidence files listed for that link in `.cairn/workspace.json`.
   - Decide, then run `cairn annotate-edge <key> --confirm` or `--reject`, adding `--why "<one line>"`.
4. Run `cairn status` again and report what changed in two or three lines.

Never edit `.cairn/workspace.json`, cards, or INDEX.md by hand; they are regenerated on every scan.
"""


def pointer_text(workspaces: Sequence[str]) -> str:
    """~60-100 tokens; global context files load in every project, so keep it a pointer."""
    listed = [f"- `{w}`" for w in workspaces] or ["- (none registered yet)"]
    return "\n".join(
        [
            "## cairn workspace maps",
            "If your working directory is inside one of these folders, or the user names a repo "
            "you can't see, read `<folder>/.cairn/INDEX.md`, then `<folder>/.cairn/cards/<repo>.md`, "
            "before exploring. The `cairn` MCP tools (resolve_repo, repo_card, related, find_across) "
            "answer the same questions.",
            *listed,
        ]
    )


def skill_markdown() -> str:
    return f"---\nname: cairn\ndescription: {SKILL_DESCRIPTION}\n---\n\n{SKILL_BODY}"


def gemini_command_toml() -> str:
    return f'description = {json.dumps(SKILL_DESCRIPTION)}\nprompt = """\n{SKILL_BODY}"""\n'


def cursor_rule_mdc(workspace: str) -> str:
    header = "---\ndescription: cairn workspace map\nalwaysApply: true\n---\n\n"
    return header + pointer_text([workspace]) + "\n"
