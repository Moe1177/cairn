from cairn.match.overrides import apply_overrides
from cairn.model.graph import Confidence, Edge, EdgeType
from cairn.model.overrides import Authored, Relations

KNOWN = frozenset({"a", "b", "c"})


def _edge(src: str, tgt: str, type_: EdgeType, conf: Confidence = Confidence.INFERRED) -> Edge:
    return Edge(source=src, target=tgt, type=type_, confidence=conf, score=0.5)


def test_remove_edges_both_directions_for_symmetric() -> None:
    edges = [_edge("a", "b", EdgeType.SHARES_DB), _edge("a", "c", EdgeType.MENTIONS)]
    relations = Relations.model_validate(
        {"remove_edges": [{"from": "b", "to": "a", "type": "shares_db"}]}
    )
    result = apply_overrides(edges, relations, {}, KNOWN)
    assert [e.key for e in result.edges] == ["a->c:mentions"]


def test_remove_all_types_when_type_omitted() -> None:
    edges = [_edge("a", "b", EdgeType.MENTIONS), _edge("a", "b", EdgeType.PATH_REF)]
    relations = Relations.model_validate({"remove_edges": [{"from": "a", "to": "b"}]})
    assert apply_overrides(edges, relations, {}, KNOWN).edges == ()


def test_reviews_and_whys() -> None:
    edges = [
        _edge("a", "b", EdgeType.MENTIONS, Confidence.AMBIGUOUS),
        _edge("a", "c", EdgeType.MENTIONS),
    ]
    authored = {
        "a": Authored(
            edge_reviews={"a->b:mentions": "confirmed", "a->c:mentions": "rejected"},
            edge_whys={"a->b:mentions": "README links the admin panel"},
        )
    }
    (edge,) = apply_overrides(edges, Relations(), authored, KNOWN).edges
    assert edge.confidence is Confidence.INFERRED
    assert edge.why == "README links the admin panel"


def test_manual_edges_and_warnings() -> None:
    relations = Relations.model_validate(
        {
            "edges": [
                {"from": "a", "to": "b", "note": "use the API"},
                {"from": "a", "to": "ghost"},
            ],
            "aliases": {"phantom": ["p"]},
            "notes": {"nobody": "x"},
        }
    )
    result = apply_overrides([], relations, {}, KNOWN)
    (manual,) = result.edges
    assert manual.type is EdgeType.MANUAL and manual.confidence is Confidence.EXTRACTED
    assert manual.note == "use the API" and manual.signals == ("manual",)
    joined = "\n".join(result.warnings)
    assert "ghost" in joined and "phantom" in joined and "nobody" in joined


def test_symmetric_edge_reviews_and_whys_match_either_direction() -> None:
    # Final review I6: shares_db direction is invisible to users and can flip.
    edges = [_edge("a", "b", EdgeType.SHARES_DB), _edge("a", "c", EdgeType.SHARES_DB)]
    authored = {
        "b": Authored(edge_reviews={"b->a:shares_db": "rejected"}),
        "c": Authored(edge_whys={"c->a:shares_db": "same Postgres instance"}),
    }
    (edge,) = apply_overrides(edges, Relations(), authored, KNOWN).edges
    assert edge.key == "a->c:shares_db" and edge.why == "same Postgres instance"


def test_corroboration_ignores_ambiguous_and_rejected_edges() -> None:
    # Phase 2a review I4
    db = Edge(
        source="a", target="b", type=EdgeType.SHARES_DB, confidence=Confidence.AMBIGUOUS, score=0.3
    )
    weak_pkg = _edge("a", "b", EdgeType.DEPENDS_ON_PACKAGE, Confidence.AMBIGUOUS)
    (still_db, _) = apply_overrides([db, weak_pkg], Relations(), {}, KNOWN).edges
    assert still_db.confidence is Confidence.AMBIGUOUS
    mention = _edge("b", "a", EdgeType.MENTIONS)
    authored = {"b": Authored(edge_reviews={"b->a:mentions": "rejected"})}
    (only,) = apply_overrides([db, mention], Relations(), authored, KNOWN).edges
    assert only.confidence is Confidence.AMBIGUOUS
    assert not any(s.startswith("corroborated:") for s in only.signals)
    (upgraded, _) = apply_overrides([db, mention], Relations(), {}, KNOWN).edges
    assert upgraded.confidence is Confidence.INFERRED
