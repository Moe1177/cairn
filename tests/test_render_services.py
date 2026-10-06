"""Phase 2d Task 6: cards and MCP describe service links in plain words (spec §21.5)."""

from pathlib import Path

import pytest

from cairn.emit import write_outputs
from cairn.mcp_server import tools
from cairn.model.graph import Confidence, Edge, EdgeType
from cairn.render.card import relate_line
from cairn.scan import scan_workspace
from tests.helpers import make_repo


def _edge(type_: EdgeType, signals: tuple[str, ...]) -> Edge:
    return Edge(
        source="gateway",
        target="trips-svc",
        type=type_,
        confidence=Confidence.INFERRED,
        score=0.6,
        signals=signals,
    )


@pytest.mark.parametrize(
    ("type_", "signals", "expected"),
    [
        (
            EdgeType.CALLS_HTTP,
            (
                "http_route:/trips/{}",
                "http_route:/trips",
                "http_route:/fares/{}",
                "http_route:/a/b",
            ),
            "calls /trips/{}, /trips, /fares/{} +1 more",
        ),
        (EdgeType.GRPC, ("grpc:TripsService",), "gRPC TripsService"),
        (EdgeType.PUBSUB, ("topic:trip.completed",), "publishes trip.completed"),
        (EdgeType.COMPOSE_LINK, ("compose:depends_on",), "compose: depends on"),
        (
            EdgeType.SHARES_ENV,
            ("env:TRIPS_SVC_URL", "env:TRIPS_KEY"),
            "shares env TRIPS_SVC_URL, TRIPS_KEY",
        ),
    ],
)
def test_relate_lines(type_: EdgeType, signals: tuple[str, ...], expected: str) -> None:
    assert f"→ trips-svc: {expected} (inferred)" == relate_line("gateway", _edge(type_, signals))


def test_find_across_lists_routes_and_topics_but_not_internal_compose_facts(tmp_path: Path) -> None:
    make_repo(
        tmp_path,
        "trips-svc",
        {"app.py": '@app.get("/trips/{id}")\nproducer.send("trip.completed", b"")'},
    )
    make_repo(
        tmp_path,
        "infra",
        {
            "docker-compose.yml": "services:\n  a:\n    build: ../trips-svc\n    depends_on: [b]\n  b:\n    image: redis\n"
        },
    )
    write_outputs(tmp_path, scan_workspace(tmp_path))
    assert "trips-svc exposes http route '/trips/{}'" in tools.find_across_text(
        tmp_path, "/trips", "http_route"
    )
    assert "trips-svc exposes topic 'trip.completed'" in tools.find_across_text(tmp_path, "trip.")
    assert "=>" not in tools.find_across_text(tmp_path, "trips")
