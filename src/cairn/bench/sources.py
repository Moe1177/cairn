"""Fetch an OSS suite's repos at their pinned commits (spec §11 E2 workspace 2).

Each source is cloned shallowly at its exact SHA into `<suite>/.sources/<stamp>/<name>/`, its
`.git` dropped and binary assets (images, fonts, archives) removed, then marked as a fixture repo
so the harness materialises it like any other suite. Fetched code is only ever read: no hooks
exist in a fresh clone, symlinks are checked out as plain files, and nothing is built or run.
"""

import contextlib
import hashlib
import shutil
import subprocess
from pathlib import Path

from cairn.bench.suite import Source, Suite
from cairn.errors import CairnError

SOURCES_DIR = ".sources"
_COMPLETE = ".complete"
_BINARY_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".webp",
        ".bmp",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".otf",
        ".mp4",
        ".webm",
        ".mp3",
        ".zip",
        ".gz",
        ".tgz",
        ".jar",
        ".war",
        ".pdf",
        ".psd",
    }
)
_GIT = ("git", "-c", "core.symlinks=false", "-c", "advice.detachedHead=false")
_TIMEOUT = 600


def fetch_sources(suite_dir: Path, suite: Suite) -> Path:
    """The folder of fixture repos for `suite`: its own fixtures, or its sources fetched once."""
    if not suite.sources:
        return suite_dir / suite.workspace
    stamp = hashlib.sha1(
        "\n".join(f"{s.name} {s.url} {s.sha}" for s in suite.sources).encode()
    ).hexdigest()[:12]
    root = suite_dir / SOURCES_DIR
    target = root / stamp
    if (target / _COMPLETE).is_file():
        return target
    staging = root / f".tmp-{stamp}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    for source in suite.sources:
        _fetch_one(source, staging / source.name)
    (staging / _COMPLETE).write_text("", encoding="utf-8")
    shutil.rmtree(target, ignore_errors=True)
    staging.rename(target)
    return target


def remotes(suite: Suite) -> dict[str, str]:
    """name -> upstream URL, so the materialised repos carry their real remotes."""
    return {s.name: s.url for s in suite.sources if s.url.startswith("https://")}


def _fetch_one(source: Source, dest: Path) -> None:
    dest.mkdir(parents=True)
    for args in (
        ["init", "-q"],
        ["fetch", "-q", "--depth", "1", source.url, source.sha],
        ["checkout", "-q", "FETCH_HEAD"],
    ):
        try:
            done = subprocess.run(
                [*_GIT, "-C", str(dest), *args],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise CairnError(f"couldn't fetch {source.name} ({source.url}): {exc}") from exc
        if done.returncode != 0:
            detail = (done.stderr.strip().splitlines() or ["git failed"])[-1][:300]
            raise CairnError(f"couldn't fetch {source.name} at {source.sha[:12]}: {detail}")
    _remove_tree(dest / ".git")
    for path in sorted(dest.rglob("*"), reverse=True):
        if path.is_file() and path.suffix.lower() in _BINARY_SUFFIXES:
            path.unlink()
    (dest / ".fixture-repo").write_text("", encoding="utf-8")


def _remove_tree(path: Path) -> None:
    """Git marks pack files read-only, which Windows won't delete: clear that first."""
    for item in path.rglob("*"):
        with contextlib.suppress(OSError):
            item.chmod(0o700)
    shutil.rmtree(path)
