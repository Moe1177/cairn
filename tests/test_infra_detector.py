"""Phase 2d Task 4: compose dependencies, gRPC and pub/sub (spec §21.2)."""

import time
from pathlib import Path

import pytest

from cairn.detectors import LIVE_DETECTOR_IDS
from cairn.detectors.infra import InfraDetector
from cairn.detectors.messaging import MessagingDetector
from cairn.model.graph import Confidence, EdgeType, FactKind
from cairn.scan import scan_workspace
from tests.helpers import ctx_for, make_repo, write

COMPOSE = """
services:
  gateway:
    build:
      context: ../gateway
    depends_on:
      - trips
      - billing
  trips:
    build: ../trips-svc
    depends_on: {postgres: {condition: service_healthy}}
  billing:
    image: ghcr.io/acme/billing:1.4
  ghost:
    build: ../not-cloned
  postgres:
    image: postgres:16
"""


def _edges(ws: Path, kind: EdgeType) -> dict[tuple[str, str], Confidence]:
    return {
        (e.source, e.target): e.confidence
        for e in scan_workspace(ws).workspace.edges
        if e.type is kind
    }


def test_compose_depends_on_links_the_built_repos(tmp_path: Path) -> None:
    make_repo(tmp_path, "infra", {"docker-compose.yml": COMPOSE})
    make_repo(tmp_path, "gateway")
    make_repo(tmp_path, "trips-svc")
    make_repo(tmp_path, "billing")
    assert _edges(tmp_path, EdgeType.COMPOSE_LINK) == {
        ("gateway", "trips-svc"): Confidence.EXTRACTED,
        ("gateway", "billing"): Confidence.EXTRACTED,
    }
    assert "infra" in LIVE_DETECTOR_IDS


def test_compose_detector_ignores_unparseable_files(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "infra", {"docker-compose.yml": "services: [unclosed"})
    assert InfraDetector().run(ctx_for(tmp_path, repo)).consumes == ()


GRPC_SERVER = {
    "go": ("server.go", "pb.RegisterTripsServiceServer(s, &server{})"),
    "py": ("server.py", "trips_pb2_grpc.add_TripsServiceServicer_to_server(Servicer(), server)"),
    "ts": ("server.ts", "server.addService(TripsServiceService, impl)"),
    "java": ("Svc.java", "public class Svc extends TripsServiceGrpc.TripsServiceImplBase {"),
}
GRPC_CLIENT = {
    "go": ("client.go", "c := pb.NewTripsServiceClient(conn)"),
    "py": ("client.py", "stub = trips_pb2_grpc.TripsServiceStub(channel)"),
    "ts": ("client.ts", "const c = new TripsServiceClient(addr, creds)"),
}


@pytest.mark.parametrize("server", sorted(GRPC_SERVER))
@pytest.mark.parametrize("client", sorted(GRPC_CLIENT))
def test_grpc_client_links_to_the_implementer(tmp_path: Path, server: str, client: str) -> None:
    make_repo(tmp_path, "trips-svc", dict([GRPC_SERVER[server]]))
    make_repo(tmp_path, "gateway", dict([GRPC_CLIENT[client]]))
    make_repo(
        tmp_path,
        "protos",
        {"trips.proto": "service TripsService {\n  rpc Get(Req) returns (Res);\n}"},
    )
    assert _edges(tmp_path, EdgeType.GRPC) == {("gateway", "trips-svc"): Confidence.INFERRED}


def test_a_proto_definition_alone_makes_no_edge(tmp_path: Path) -> None:
    make_repo(tmp_path, "protos", {"trips.proto": "service TripsService {}"})
    make_repo(tmp_path, "gateway", {"c.go": "pb.NewTripsServiceClient(conn)"})
    assert _edges(tmp_path, EdgeType.GRPC) == {}


def test_kafka_publisher_links_to_subscriber(tmp_path: Path) -> None:
    make_repo(
        tmp_path,
        "trips-svc",
        {"events.ts": "await producer.send({ topic: 'trip.completed', messages: [m] })"},
    )
    make_repo(tmp_path, "receipts", {"worker.py": "consumer.subscribe(['trip.completed'])"})
    make_repo(
        tmp_path,
        "ledger",
        {"Listener.java": '@KafkaListener(topics = "trip.completed")'},
    )
    assert _edges(tmp_path, EdgeType.PUBSUB) == {
        ("trips-svc", "receipts"): Confidence.INFERRED,
        ("trips-svc", "ledger"): Confidence.INFERRED,
    }


def test_vague_topics_and_multiple_publishers(tmp_path: Path) -> None:
    make_repo(
        tmp_path, "a", {"p.py": "producer.send('events', b'x')\nproducer.send('order.paid', b'x')"}
    )
    make_repo(tmp_path, "b", {"p.py": "producer.send('order.paid', b'x')"})
    make_repo(tmp_path, "c", {"s.py": "consumer.subscribe(['events', 'order.paid'])"})
    edges = _edges(tmp_path, EdgeType.PUBSUB)
    assert set(edges) == {("a", "c"), ("b", "c")}
    assert all(conf is Confidence.AMBIGUOUS for conf in edges.values())


def test_messaging_facts(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path,
        "svc",
        {
            "a.go": 'pb.RegisterBillingServer(s, b)\nnc.Publish("billing.charged", data)',
            "b.py": "stub = GeoServiceStub(ch)\nnc.subscribe('geo.updated')",
        },
    )
    result = MessagingDetector().run(ctx_for(tmp_path, repo))
    exposes = {(f.kind, f.value) for f in result.exposes}
    consumes = {(f.kind, f.value) for f in result.consumes}
    assert (FactKind.GRPC_SERVICE, "Billing") in exposes
    assert (FactKind.TOPIC, "billing.charged") in exposes
    assert (FactKind.GRPC_SERVICE, "GeoService") in consumes
    assert (FactKind.TOPIC, "geo.updated") in consumes


HOSTILE = {
    "sends": "producer.send('" + "a" * 900_000,
    "many": "pb.NewXClient(c) " * 60_000,
    "compose": "services:\n" + "  s: {depends_on: [" + "x," * 300_000,
}


@pytest.mark.parametrize("name", sorted(HOSTILE))
def test_infra_and_messaging_are_linear(tmp_path: Path, name: str) -> None:
    repo = make_repo(tmp_path, "svc")
    write(repo, "docker-compose.yml" if name == "compose" else "big.go", HOSTILE[name][:999_000])
    ctx = ctx_for(tmp_path, repo)
    start = time.perf_counter()
    InfraDetector().run(ctx)
    MessagingDetector().run(ctx)
    assert time.perf_counter() - start < 1.5
