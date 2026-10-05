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
    authored = load_authored(ws)
    assert path.name == "a.yaml"  # stored under the edge's canonical key a->b
    assert authored["b"].summary == "Billing service" and authored["b"].aliases == ("billing",)
    assert authored["a"].edge_reviews == {"a->b:shares_db": "rejected"}
    assert authored["a"].edge_whys == {"a->b:shares_db": "different databases"}


def test_unknown_edge_is_refused_and_nothing_written(tmp_path: Path) -> None:
    # Review Focus 2
    ws = _ws(tmp_path)
    with pytest.raises(CairnError):
        annotate_edge(ws, "a->b:mentions", review="confirmed", why=None)
    assert not (ws / ".cairn" / "authored").exists()


def test_annotating_without_a_map_is_refused(tmp_path: Path) -> None:
    with pytest.raises(CairnError):
        annotate_edge(tmp_path, "a->b:shares_db", review="confirmed", why=None)


def _rescan(ws: Path) -> None:
    write_outputs(ws, scan_workspace(ws))


def test_a_rejection_can_be_undone(tmp_path: Path) -> None:
    # Phase 2a review I2
    ws = _ws(tmp_path)
    annotate_edge(ws, "a->b:shares_db", review="rejected", why=None)
    _rescan(ws)
    annotate_edge(ws, "a->b:shares_db", review="confirmed", why="same Postgres")
    assert load_authored(ws)["a"].edge_reviews == {"a->b:shares_db": "confirmed"}


def test_flipped_keys_are_stored_canonically_and_stale_ones_removed(tmp_path: Path) -> None:
    # Phase 2a review I3: the newest decision must win regardless of key direction.
    ws = _ws(tmp_path)
    write(ws, ".cairn/authored/b.yaml", "edge_reviews:\n  b->a:shares_db: confirmed\n")
    annotate_edge(ws, "b->a:shares_db", review="rejected", why=None)
    authored = load_authored(ws)
    assert authored["a"].edge_reviews == {"a->b:shares_db": "rejected"}
    assert authored.get("b") is None or "b->a:shares_db" not in authored["b"].edge_reviews


def test_old_explanation_is_carried_to_the_canonical_key(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    write(ws, ".cairn/authored/b.yaml", "edge_whys:\n  b->a:shares_db: same Postgres\n")
    annotate_edge(ws, "a->b:shares_db", review="confirmed", why=None)
    authored = load_authored(ws)
    assert authored["a"].edge_whys == {"a->b:shares_db": "same Postgres"}
    assert "b->a:shares_db" not in authored["b"].edge_whys


def test_set_summary_keeps_reviews_and_merges_aliases(tmp_path: Path) -> None:
    from cairn.authored_store import set_summary

    ws = _ws(tmp_path)
    write(
        ws,
        ".cairn/authored/a.yaml",
        "aliases: [billing]\nedge_reviews:\n  a->b:shares_db: rejected\n",
    )
    set_summary(ws, "a", "  Billing   service for invoices. ", aliases=("Ledger", "billing"))
    authored = load_authored(ws)["a"]
    assert authored.summary == "Billing service for invoices."
    assert authored.aliases == ("billing", "ledger")
    assert authored.edge_reviews == {"a->b:shares_db": "rejected"}


def test_set_summary_rejects_unknown_repo_and_bad_text(tmp_path: Path) -> None:
    # Review Focus 4
    from cairn.authored_store import set_summary

    ws = _ws(tmp_path)
    with pytest.raises(CairnError) as info:
        set_summary(ws, "aa", "x y")
    assert "Did you mean" in str(info.value)
    with pytest.raises(CairnInputError):
        set_summary(ws, "a", "   ")
    with pytest.raises(CairnInputError):
        set_summary(ws, "a", "x" * 501)
    assert not (ws / ".cairn" / "authored").exists()
