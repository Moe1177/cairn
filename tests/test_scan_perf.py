"""Phase 5 Task 1: one walk and one read per file per repo (spec §22), with identical output."""

import json
import os
import re
from collections import Counter
from pathlib import Path

import pytest

import cairn.detectors.base as base_module
import cairn.discover.files as files_module
from cairn.bench.workspace import materialize
from cairn.scan import scan_workspace
from tests.helpers import make_repo

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "workspaces"
GOLDEN = Path(__file__).resolve().parent / "golden"
WORKSPACES = sorted(p.name for p in FIXTURES.iterdir() if p.is_dir())


def _facts(ws: Path) -> dict:
    """Everything detectors produce, minus what varies per checkout (SHAs, times)."""
    workspace = scan_workspace(ws, use_cache=False).workspace
    return {
        "repos": {
            r.id: {
                "stack": list(r.stack),
                "aliases": list(r.aliases),
                "contracts": _stable(r.contracts.model_dump(mode="json")),
                "layout": [e.model_dump(mode="json") for e in r.layout],
                "packages": [p.model_dump(mode="json") for p in r.packages],
                "commands": [c.model_dump(mode="json") for c in r.commands],
                "errors": [e.model_dump(mode="json") for e in r.detector_errors],
            }
            for r in workspace.repos
        },
        "edges": [_stable_edge(e.model_dump(mode="json")) for e in workspace.edges],
    }


def _stable_edge(edge: dict) -> dict:
    """A family link's `root:<sha>` signal changes with every fixture checkout: mask the sha."""
    signals = [("root:<sha>" if s.startswith("root:") else s) for s in edge["signals"]]
    return {**edge, "signals": signals}


def _stable(contracts: dict) -> dict:
    """Root-commit facts differ on every fixture checkout (like SHAs): leave them out."""
    return {
        side: [f for f in facts if f["kind"] != "git_root"] for side, facts in contracts.items()
    }


@pytest.mark.parametrize("name", WORKSPACES)
def test_scan_output_is_unchanged(tmp_path: Path, name: str) -> None:
    ws = materialize(FIXTURES / name, tmp_path / name).resolve()
    golden = GOLDEN / f"{name}.json"
    got = json.dumps(_facts(ws), indent=1, sort_keys=True)
    if os.environ.get("CAIRN_WRITE_GOLDEN"):
        golden.write_text(got + "\n", encoding="utf-8", newline="\n")
    assert got + "\n" == golden.read_text(encoding="utf-8")


def _repos(tmp_path: Path) -> Path:
    for name in ("api", "web"):
        repo = make_repo(tmp_path, name)
        (repo / "src").mkdir(exist_ok=True)
        for i in range(5):
            (repo / "src" / f"m{i}.py").write_text(
                "import os\nrequests.get(os.environ['API_URL'] + '/users')\n", encoding="utf-8"
            )
    return tmp_path


def test_each_repo_is_walked_once_per_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _repos(tmp_path)
    walks: Counter[str] = Counter()
    real = files_module.os.walk

    def counting(top, *args, **kwargs):  # type: ignore[no-untyped-def]
        walks[Path(top).name] += 1
        return real(top, *args, **kwargs)

    monkeypatch.setattr(files_module.os, "walk", counting)
    scan_workspace(root, use_cache=False)
    # the live detectors reuse the read phase's file list (was 6 walks)
    assert walks["api"] == 1 and walks["web"] == 1, walks


def test_each_file_is_read_at_most_once_per_phase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repos(tmp_path)
    reads: Counter[str] = Counter()
    real = base_module.read_text

    def counting(path: Path, max_bytes: int = 1_000_000) -> str | None:
        reads[path.relative_to(root).as_posix()] += 1
        return real(path, max_bytes)

    monkeypatch.setattr(base_module, "read_text", counting)
    scan_workspace(root, use_cache=False)
    sources = {k: v for k, v in reads.items() if k.endswith(".py")}
    assert sources and max(sources.values()) == 1, sources


def test_the_read_cache_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(base_module, "READ_CACHE_BYTES", 2_000)
    repo = make_repo(tmp_path, "big")
    for i in range(10):
        (repo / f"f{i}.py").write_text("x = 1\n" * 100, encoding="utf-8")
    from cairn.config import CairnConfig
    from cairn.discover.repos import RepoLocation

    ctx = base_module.DetectorContext(
        tmp_path, RepoLocation(id="big", root=repo, app_roots=(repo,)), CairnConfig()
    )
    for path in ctx.files(lambda name: name.endswith(".py")):
        assert ctx.read(path) is not None
    assert ctx.cached_bytes() <= 2_000


class _Counting:
    """Stands in for a compiled pattern and counts how often a detector runs it."""

    def __init__(self, pattern: "re.Pattern[str]", counter: Counter[str]) -> None:
        self.pattern, self.counter = pattern, counter

    def finditer(self, text: str):  # type: ignore[no-untyped-def]
        self.counter["finditer"] += 1
        return self.pattern.finditer(text)

    def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
        return getattr(self.pattern, name)


def test_lines_without_gate_keywords_skip_the_regexes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cairn.detectors.database as database
    import cairn.detectors.http as http
    import cairn.detectors.messaging as messaging

    counter: Counter[str] = Counter()
    wrap = lambda patterns: tuple(_Counting(p, counter) for p in patterns)  # noqa: E731
    monkeypatch.setattr(messaging, "_GRPC_SERVE", wrap(messaging._GRPC_SERVE))
    monkeypatch.setattr(messaging, "_PUBLISH", wrap(messaging._PUBLISH))
    monkeypatch.setattr(
        http, "_ROUTES", {k: _Counting(v, counter) for k, v in http._ROUTES.items()}
    )
    monkeypatch.setattr(http, "_CALLS", {k: _Counting(v, counter) for k, v in http._CALLS.items()})
    monkeypatch.setattr(database, "SQL_REF", _Counting(database.SQL_REF, counter))
    repo = make_repo(tmp_path, "plain")
    (repo / "calc.py").write_text("x = 1\ny = x * 2\n" * 200, encoding="utf-8")
    scan_workspace(tmp_path, use_cache=False)
    assert counter["finditer"] == 0, counter


def test_live_detectors_run_in_the_worker_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    import cairn.detectors as registry
    from cairn.detectors.base import DetectorResult

    threads: list[str] = []

    class Recorder:
        id = "docs"

        def run(self, ctx: base_module.DetectorContext) -> DetectorResult:
            threads.append(threading.current_thread().name)
            return DetectorResult()

    others = tuple(d for d in registry.RELATION_DETECTORS if d.id != "docs")
    monkeypatch.setattr(registry, "RELATION_DETECTORS", (*others, Recorder()))
    _repos(tmp_path)
    scan_workspace(tmp_path, use_cache=False)
    assert len(threads) == 2 and "MainThread" not in threads, threads
