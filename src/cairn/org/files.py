"""Finding your way in an org repo nobody cloned: what a folder holds, and which file a path
that isn't there most likely meant (an agent can't list an uncloned repo, so a wrong guess at
a name's case or folder would otherwise be a dead end)."""

import difflib
import posixpath
import re
from collections.abc import Sequence

from cairn.security.text import clean_inline

MAX_ENTRIES = 200  # a folder's listing: enough to pick from, not a dump of a monorepo
MAX_NEAR = 8
_PATH_CHARS = 300
_SEPARATORS = re.compile(r"[^a-z0-9]")


def folder_entries(paths: Sequence[str], folder: str) -> list[str]:
    """What `folder` ("" for the root) holds: its subfolders (ending in /) first, then its
    files. Empty when no file is under it."""
    prefix = f"{folder.strip('/')}/" if folder.strip("/") else ""
    folders: set[str] = set()
    files: set[str] = set()
    for path in paths:
        if not path.startswith(prefix):
            continue
        head, sep, _ = path[len(prefix) :].partition("/")
        (folders if sep else files).add(f"{head}/" if sep else head)
    return sorted(folders, key=str.lower) + sorted(files, key=str.lower)


def _squash(name: str) -> str:
    return _SEPARATORS.sub("", name.lower())


def near_paths(paths: Sequence[str], wanted: str) -> list[str]:
    """The repo's files `wanted` most likely meant: the same path in another case, then files
    of the same name (read_config.go for readConfig.go) anywhere, then paths spelled alike."""
    wanted = wanted.strip("/")
    lowered = wanted.lower()
    name = _squash(posixpath.basename(wanted))
    found = [p for p in paths if p.lower() == lowered]
    found += sorted(
        (p for p in paths if name and _squash(posixpath.basename(p)) == name),
        key=lambda p: (p.count("/"), p.lower()),
    )
    by_lower = {p.lower(): p for p in paths}
    found += [by_lower[p] for p in difflib.get_close_matches(lowered, by_lower, n=4, cutoff=0.75)]
    return list(dict.fromkeys(found))[:MAX_NEAR]


def nearest_folder(paths: Sequence[str], wanted: str) -> str:
    """The deepest folder of `wanted`'s that the repo has ("" for the root)."""
    folder = posixpath.dirname(wanted.strip("/"))
    while folder and not any(p.startswith(f"{folder}/") for p in paths):
        folder = posixpath.dirname(folder)
    return folder


def render_folder(repo: str, folder: str, entries: Sequence[str], *, cut: bool) -> str:
    shown = entries[:MAX_ENTRIES]
    where = f"{repo}/{folder.strip('/')}/" if folder.strip("/") else f"{repo}/"
    lines = [f"{_safe(where)} (a folder: read_org_file one of these)"]
    lines += [f"- {_safe(entry)}" for entry in shown]
    if len(entries) > len(shown):
        lines.append(f"… {len(entries) - len(shown)} more")
    if cut:
        lines.append("(the repo's file list was cut short: this folder may hold more)")
    return "\n".join(lines)


def render_missing(repo: str, wanted: str, paths: Sequence[str], *, cut: bool) -> str:
    """No file `wanted` in `repo`: the files it most likely meant, or else what its nearest
    folder holds."""
    wanted = wanted.strip("/")
    head = f"No file {_safe(wanted)} in {repo}"
    if cut:
        head += " (the repo's file list was cut short, so it may still be there)"
    near = near_paths(paths, wanted)
    if near:
        return "\n".join([f"{head}. Did you mean:", *(f"- {_safe(p)}" for p in near)])
    folder = nearest_folder(paths, wanted)
    entries = folder_entries(paths, folder)
    if not entries:
        return f"{head}: its default branch has no files."
    return f"{head}.\n" + render_folder(repo, folder, entries, cut=False)


def _safe(path: str) -> str:
    """A path as one inert line: a repo's file names are its authors' text, not cairn's."""
    return clean_inline(path, _PATH_CHARS)
