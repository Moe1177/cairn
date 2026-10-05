import pytest
from pydantic import ValidationError

from cairn.errors import CairnError, CairnInputError
from cairn.model.graph import (
    Confidence,
    Contracts,
    Edge,
    EdgeType,
    Evidence,
    Fact,
    FactKind,
    Repo,
    Workspace,
)


def _workspace() -> Workspace:
    ev = Evidence(repo="admin", file="lib/q.ts", line=3, snippet="SELECT * FROM orders")
    admin = Repo(
        id="admin",
        path="admin",
        contracts=Contracts(
            consumes=(Fact(kind=FactKind.DB_TABLE, value="orders", evidence=(ev,)),)
        ),
    )
    app = Repo(id="app", path="app")
    edge = Edge(
        source="admin",
        target="app",
        type=EdgeType.SHARES_DB,
        confidence=Confidence.INFERRED,
        score=0.6,
        signals=("db_table:orders",),
        evidence=(ev,),
    )
    return Workspace(
        workspace_root="/ws",
        generated_at="2026-10-05T00:00:00+00:00",
        repos=(admin, app),
        edges=(edge,),
    )


def test_workspace_round_trips_through_json() -> None:
    ws = _workspace()
    assert Workspace.model_validate_json(ws.model_dump_json()) == ws


def test_models_are_frozen() -> None:
    ws = _workspace()
    with pytest.raises(ValidationError):
        ws.repos[0].id = "other"  # type: ignore[misc]


def test_edge_key_format() -> None:
    assert _workspace().edges[0].key == "admin->app:shares_db"


def test_confidence_rank_orders_tiers() -> None:
    assert Confidence.EXTRACTED.rank > Confidence.INFERRED.rank > Confidence.AMBIGUOUS.rank


def test_evidence_line_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Evidence(repo="r", file="f", line=0, snippet="")


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Repo.model_validate({"id": "r", "path": "r", "surprise": 1})


def test_workspace_lookups() -> None:
    ws = _workspace()
    assert ws.repo("app") is not None
    assert ws.repo("missing") is None
    assert len(ws.edges_for("app")) == 1
    assert ws.edges_for("nobody") == ()


def test_input_error_message_includes_path() -> None:
    err = CairnInputError("relations.yaml", "edges.0.from: field required")
    assert isinstance(err, CairnError)
    assert str(err) == "relations.yaml: edges.0.from: field required"
