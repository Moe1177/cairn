from pathlib import Path

import pytest

from cairn.authored_store import annotate_edge, parse_edge_key
from cairn.emit import write_outputs
from cairn.errors import CairnError, CairnInputError
from cairn.load import load_authored
from cairn.model.graph import EdgeType
from cairn.scan import scan_workspace
from tests.helpers import make_repo, write

SQL = "CREATE TABLE invoices (id int);\nCREATE TABLE ledgers (id int);\n"


def _ws(tmp_path: Path) -> Path:
    make_repo(tmp_path, "a", {"db/1.sql": SQL})
    make_repo(tmp_path, "b", {"db/1.sql": SQL})
    write_outputs(tmp_path, scan_workspace(tmp_path))
    return tmp_path


def test_parse_edge_key() -> None:
    assert parse_edge_key("a->b-c:shares_db") == ("a", "b-c", EdgeType.SHARES_DB)
    with pytest.raises(CairnInputError):
        parse_edge_key("a->b:not_a_type")
    with pytest.raises(CairnInputError):
        parse_edge_key("nonsense")


def test_reject_preserves_other_authored_fields(tmp_path: Path) -> None:
    # Review Focus 3
    ws = _ws(tmp_path)
    write(ws, ".cairn/authored/b.yaml", "summary: Billing service\naliases: [billing]\n")
    path = annotate_edge(ws, "b->a:shares_db", review="rejected", why="different databases")
    authored = load_authored(ws)["b"]
    assert path.name == "b.yaml"
    assert authored.summary == "Billing service" and authored.aliases == ("billing",)
    assert authored.edge_reviews == {"b->a:shares_db": "rejected"}
    assert authored.edge_whys == {"b->a:shares_db": "different databases"}


def test_unknown_edge_is_refused_and_nothing_written(tmp_path: Path) -> None:
    # Review Focus 2
    ws = _ws(tmp_path)
    with pytest.raises(CairnError):
        annotate_edge(ws, "a->b:mentions", review="confirmed", why=None)
    assert not (ws / ".cairn" / "authored").exists()


def test_annotating_without_a_map_is_refused(tmp_path: Path) -> None:
    with pytest.raises(CairnError):
        annotate_edge(tmp_path, "a->b:shares_db", review="confirmed", why=None)
