from pathlib import Path

from cairn.bench.suite import load_suite
from cairn.bench.workspace import materialize
from cairn.scan import scan_workspace

SUITE = Path(__file__).resolve().parents[1] / "bench" / "suites" / "shopverse"


def test_shopverse_suite_loads_and_tasks_reference_real_files(tmp_path: Path) -> None:
    suite = load_suite(SUITE)
    categories = {t.category for t in suite.tasks}
    assert len(suite.tasks) == 6 and categories >= {"orientation", "localization", "control"}
    ws = materialize(SUITE / suite.workspace, tmp_path / "ws")
    for task in suite.tasks:
        assert (ws / task.repo).is_dir()
        for rel in task.expect_files:
            assert (ws / rel).is_file(), rel


def test_shopverse_map_finds_the_core_relationships(tmp_path: Path) -> None:
    ws = materialize(SUITE / load_suite(SUITE).workspace, tmp_path / "ws")
    edges = {
        (*sorted((e.source, e.target)), e.type.value) for e in scan_workspace(ws).workspace.edges
    }
    assert ("orders-svc", "payments-svc", "shares_db") in edges
    assert ("admin", "orders-svc", "shares_db") in edges
    assert ("shared-types", "storefront", "depends_on_package") in edges
