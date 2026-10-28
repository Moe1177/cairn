"""Sessions that start with only their own repo in view (`cairn bench --scope repo`).

A session opened in one repo of an org sees that repo, and reaches the org's other repos only
through cairn's org tools: they aren't on disk. Each task's repo gets a workspace of its own, in
a temp folder of its own, with the suite's org configured and the org's caches warm, as a user
who has used cairn with the org before would have them. The session is denied every other
folder of the run (bench/runner.py). Answers are still graded against the whole pinned
workspace.

Only condition E has the org tools; A to D can name the org's repos (C and D from INDEX) but
not read them, so a task whose answer lies in another repo is out of their reach by design.
"""

import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path

import yaml

from cairn.bench.suite import Task
from cairn.config import OrgSource
from cairn.errors import CairnError
from cairn.mcp_server.tools import packages_text, profile_text
from cairn.org.access import org_repo, with_client
from cairn.org.view import catalog_index
from cairn.paths import authored_dir, cairn_dir, config_file
from cairn.store.atomic import atomic_write_text

SCOPES = ("workspace", "repo")


def write_org_config(ws: Path, org: OrgSource) -> None:
    entry = org.model_dump(mode="json", exclude_defaults=True)
    entry["org"] = org.org  # never a default, but say it whatever pydantic decides
    atomic_write_text(config_file(ws), yaml.safe_dump({"orgs": [entry]}, sort_keys=False))


def prepare_org(
    cache_ws: Path, org: OrgSource, tasks: Sequence[Task], ws: Path
) -> dict[str, list[str]]:
    """Read the org's catalog, packages and profile into `cache_ws`'s caches (what INDEX's org
    section and the org tools start from: no session pays for the first read, so timings don't
    depend on task order), and return what each task's answer lost on the org's default branch:
    the suite pins older commits (`ws`), and the org tools read the latest."""
    write_org_config(cache_ws, org)
    catalog_index(cache_ws, org)
    packages_text(cache_ws, org=org.org)
    profile_text(cache_ws, org.org)
    drift = {task.id: _drift(org, task, ws) for task in tasks}
    return {task: lost for task, lost in drift.items() if lost}


def _drift(org: OrgSource, task: Task, ws: Path) -> list[str]:
    """The task's answer files outside its repo that the org no longer has (or that couldn't be
    checked), and the keywords those files held at the pinned commit and no longer hold (a
    version pin bumped since: an agent reading the org gives the new one)."""
    lost: list[str] = []
    pinned: list[str] = []
    latest: list[str] = []
    for path in task.expect_files:
        repo, _, inside = path.partition("/")
        if repo == task.repo:
            continue  # on disk, at the pinned commit
        full = org_repo(org, repo)
        try:
            text = with_client(org, lambda c, f=full, i=inside: c.read_file(f, i))
            there = text is not None or with_client(
                org, lambda c, f=full, i=inside: c.file_exists(f, i)
            )
        except CairnError as exc:
            lost.append(f"{path} (unchecked: {exc})")
            continue
        if not there:
            lost.append(path)
        elif text is not None and (ws / path).is_file():  # binary or too big: nothing to compare
            pinned.append((ws / path).read_text(encoding="utf-8", errors="replace").lower())
            latest.append(text.lower())
    for keyword in task.expect_keywords:
        word = keyword.lower()
        if any(word in p for p in pinned) and not any(word in t for t in latest):
            lost.append(f"keyword {keyword!r}")
    return lost


def solo_workspace(
    ws: Path, repo: str, root: Path, org: OrgSource, cache_ws: Path
) -> tuple[Path, Path]:
    """A workspace under `root` holding only `repo` (copied from `ws`, with the suite's own
    note on it, never those on repos it doesn't have), and `root` itself: the run folder where
    set_up keeps the pristine .cairn (the org config and caches)."""
    solo = root / "ws"
    shutil.copytree(ws / repo, solo / repo, symlinks=True)
    note = authored_dir(ws) / f"{repo}.yaml"
    if note.is_file():  # a summary the suite ships; set_up keeps it in the pristine copy
        authored_dir(solo).mkdir(parents=True)
        shutil.copy2(note, authored_dir(solo) / note.name)
    caches = cairn_dir(cache_ws) / "cache" / "orgs"
    if caches.is_dir():
        shutil.copytree(caches, cairn_dir(solo) / "cache" / "orgs")
    write_org_config(solo, org)
    return solo, root


def drift_note(drift: Mapping[str, Sequence[str]]) -> str:
    if not drift:
        return ""
    files = "; ".join(f"{task}: {', '.join(paths)}" for task, paths in sorted(drift.items()))
    return (
        "These answer files, or keywords in them, aren't on the org's default branch, so an "
        f"agent reading the org can't find them: {files}."
    )
