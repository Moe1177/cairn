"""Render INDEX.md: the tiny, always-loaded list of workspace repos."""

import re
from collections import Counter
from collections.abc import Mapping

from cairn.model.graph import Confidence, EdgeType, Repo, Workspace
from cairn.model.overrides import Authored
from cairn.security.text import clean_inline

INDEX_TITLE = "# Workspace repos (cairn)"
ONE_LINER_MAX = 60
_LANGUAGES = frozenset({"typescript", "javascript", "python", "go", "rust", "java"})
_PREVIEW = 8
_USED_BY_PREVIEW = 3
# Links where the source uses the target. Shared databases/env are mutual, a topic has no
# user, and a docs mention isn't use.
_USES = frozenset(
    {
        EdgeType.DEPENDS_ON_PACKAGE,
        EdgeType.CALLS_HTTP,
        EdgeType.GRPC,
        EdgeType.PATH_REF,
        EdgeType.COMPOSE_LINK,
        EdgeType.MANUAL,
    }
)


def one_liner(repo: Repo, authored: Authored | None) -> str:
    """The authored summary's first sentence. README text never enters INDEX (spec §20.1):
    INDEX is always loaded into the agent's context, so repo-controlled prose stays out."""
    text = authored.summary if authored and authored.summary else None
    if not text:
        return "no summary yet"
    first = re.split(r"(?<=[.!?])\s", " ".join(text.split()), maxsplit=1)[0].rstrip(".")
    return clean_inline(first, ONE_LINER_MAX)


def repo_line(repo: Repo, authored: Authored | None, used_by: tuple[str, ...] = ()) -> str:
    aliases = [a for a in repo.aliases if a.lower() != repo.id.lower()][:2]
    alias_part = f" ({', '.join(clean_inline(a, 64) for a in aliases)})" if aliases else ""
    stack = f" · {_primary_stack(repo.stack)}" if repo.stack else ""
    users = ""
    if used_by:
        shown = ", ".join(clean_inline(u, 40) for u in used_by[:_USED_BY_PREVIEW])
        more = len(used_by) - _USED_BY_PREVIEW
        users = f" · used by {shown}" + (f" +{more}" if more > 0 else "")
    line = f"- {clean_inline(repo.id, 80)}{alias_part}: {one_liner(repo, authored)}{stack}"
    return line + users


def used_by(workspace: Workspace) -> dict[str, tuple[str, ...]]:
    """Repo id -> the repos that use it, from directed links at least `inferred`."""
    users: dict[str, set[str]] = {}
    for edge in workspace.edges:
        if edge.type in _USES and edge.confidence.rank >= Confidence.INFERRED.rank:
            users.setdefault(edge.target, set()).add(edge.source)
    return {target: tuple(sorted(sources)) for target, sources in users.items()}


def render_index(
    workspace: Workspace,
    authored: Mapping[str, Authored],
    *,
    threshold: int = 50,
    with_cards: bool = True,
) -> str:
    if with_cards:
        lines = [
            INDEX_TITLE,
            f"Workspace root: `{workspace.workspace_root}`. Each repo's card is at "
            ".cairn/cards/<repo>.md (relative to the root).",
            "Before exploring a repo outside your working directory, read its card first.",
            "",
        ]
    else:  # benchmark condition C: the index alone
        lines = [INDEX_TITLE, f"Workspace root: `{workspace.workspace_root}`.", ""]
    if len(workspace.repos) <= threshold:
        users = used_by(workspace)
        lines += [repo_line(r, authored.get(r.id), users.get(r.id, ())) for r in workspace.repos]
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
    shown = ", ".join(clean_inline(i, 80) for i in ids[:_PREVIEW])
    return shown + (", …" if len(ids) > _PREVIEW else "")


def _group_lines(workspace: Workspace) -> list[str]:
    lines: list[str] = []
    singles: list[str] = []
    for members in _components(workspace):
        if len(members) == 1:
            singles += members
            continue
        lines.append(
            f"- group {clean_inline(_hub(members, workspace), 80)} ({len(members)} repos): "
            f"{_preview(members)}"
        )
    if singles:
        lines.append(f"- ungrouped ({len(singles)} repos): {_preview(sorted(singles))}")
    return [*lines, "", "Full list: open .cairn/cards/ (one <repo>.md per repo)."]
