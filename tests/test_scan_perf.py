"""Phase 5 Task 1: one walk and one read per file per repo (spec §22), with identical output."""

import json
import os
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
                "contracts": r.contracts.model_dump(mode="json"),
                "layout": [e.model_dump(mode="json") for e in r.layout],
                "packages": [p.model_dump(mode="json") for p in r.packages],
                "commands": [c.model_dump(mode="json") for c in r.commands],
                "errors": [e.model_dump(mode="json") for e in r.detector_errors],
            }
            for r in workspace.repos
        },
        "edges": [e.model_dump(mode="json") for e in workspace.edges],
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


def test_each_repo_is_walked_at_most_twice_per_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repos(tmp_path)
    walks: Counter[str] = Counter()
    real = files_module.os.walk

    def counting(top, *args, **kwargs):  # type: ignore[no-untyped-def]
        walks[Path(top).name] += 1
        return real(top, *args, **kwargs)

    monkeypatch.setattr(files_module.os, "walk", counting)
    scan_workspace(root, use_cache=False)
    # one walk for the identity + relation detectors, one for the live detectors (was 6)
    assert walks["api"] <= 2 and walks["web"] <= 2, walks


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
