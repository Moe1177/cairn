"""Render INDEX.md: the tiny, always-loaded list of workspace repos."""

import re
from collections import Counter
from collections.abc import Mapping

from cairn.model.graph import Confidence, Repo, Workspace
from cairn.model.overrides import Authored

INDEX_TITLE = "# Workspace repos (cairn)"
ONE_LINER_MAX = 60
_LANGUAGES = frozenset({"typescript", "javascript", "python", "go", "rust", "java"})
_PREVIEW = 8


def one_liner(repo: Repo, authored: Authored | None) -> str:
    text = (authored.summary if authored and authored.summary else None) or repo.readme_excerpt
    if not text:
        return "no summary yet"
    first = re.split(r"(?<=[.!?])\s", " ".join(text.split()), maxsplit=1)[0].rstrip(".")
    return first if len(first) <= ONE_LINER_MAX else first[: ONE_LINER_MAX - 1] + "…"


def repo_line(repo: Repo, authored: Authored | None) -> str:
    aliases = [a for a in repo.aliases if a.lower() != repo.id.lower()][:2]
    alias_part = f" ({', '.join(aliases)})" if aliases else ""
    stack = f" · {_primary_stack(repo.stack)}" if repo.stack else ""
    return f"- {repo.id}{alias_part}: {one_liner(repo, authored)}{stack}"


def render_index(
    workspace: Workspace, authored: Mapping[str, Authored], *, threshold: int = 50
) -> str:
    lines = [
        INDEX_TITLE,
        f"Workspace root: `{workspace.workspace_root}`. Each repo's card is at "
        ".cairn/cards/<repo>.md (relative to the root).",
        "Before exploring a repo outside your working directory, read its card first.",
        "",
    ]
    if len(workspace.repos) <= threshold:
        lines += [repo_line(r, authored.get(r.id)) for r in workspace.repos]
    else:
        lines += _group_lines(workspace)
    return "\n".join(lines) + "\n"


def _primary_stack(stack: tuple[str, ...]) -> str:
    frameworks = [s for s in stack if s not in _LANGUAGES]
    return frameworks[0] if frameworks else stack[0]


def _components(workspace: Workspace) -> list[list[str]]:
    parent = {r.id: r.id for r in workspace.repos}

    def find(x: str) -> str:
        while parent[x] != x:
            x = parent[x]
        return x

    for edge in workspace.edges:
        if (
            edge.confidence.rank >= Confidence.INFERRED.rank
            and edge.source in parent
            and edge.target in parent
        ):
            parent[find(edge.source)] = find(edge.target)
    groups: dict[str, list[str]] = {}
    for repo_id in sorted(parent):
        groups.setdefault(find(repo_id), []).append(repo_id)
    return sorted(groups.values(), key=lambda g: (-len(g), g[0]))


def _hub(members: list[str], workspace: Workspace) -> str:
    member_set = set(members)
    degree = Counter(
        node
        for e in workspace.edges
        if e.source in member_set and e.target in member_set
        for node in (e.source, e.target)
    )
    return min(members, key=lambda m: (-degree[m], m))


def _preview(ids: list[str]) -> str:
    return ", ".join(ids[:_PREVIEW]) + (", …" if len(ids) > _PREVIEW else "")


def _group_lines(workspace: Workspace) -> list[str]:
    lines: list[str] = []
    singles: list[str] = []
    for members in _components(workspace):
        if len(members) == 1:
            singles += members
            continue
        lines.append(
            f"- group {_hub(members, workspace)} ({len(members)} repos): {_preview(members)}"
        )
    if singles:
        lines.append(f"- ungrouped ({len(singles)} repos): {_preview(sorted(singles))}")
    return [*lines, "", "Full list: open .cairn/cards/ (one <repo>.md per repo)."]
