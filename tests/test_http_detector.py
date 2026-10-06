"""Phase 2d Task 3: HTTP routes, client calls, and calls_http edges (spec §21.1)."""

import time
from pathlib import Path

import pytest

from cairn.detectors.http import HttpDetector
from cairn.match.matcher import RepoFacts, match_edges
from cairn.model.graph import Confidence, Contracts, EdgeType, Evidence, Fact, FactKind
from cairn.scan import scan_workspace
from tests.helpers import ctx_for, make_repo, write


def _routes(tmp_path: Path, files: dict[str, str], side: str = "exposes") -> set[str]:
    repo = make_repo(tmp_path, "svc", files)
    result = HttpDetector().run(ctx_for(tmp_path, repo))
    facts = result.exposes if side == "exposes" else result.consumes
    return {f.value for f in facts if f.kind is FactKind.HTTP_ROUTE}


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        ({"app/api/trips/[id]/route.ts": "export async function GET() {}"}, {"/api/trips/{}"}),
        ({"src/app/(shop)/orders/route.js": "export function POST() {}"}, {"/orders"}),
        ({"pages/api/riders/index.ts": "export default h"}, {"/api/riders"}),
        ({"pages/api/riders/[id].ts": "export default h"}, {"/api/riders/{}"}),
        (
            {"server.js": "app.get('/trips/:id', h)\nrouter.post(\"/trips\", h)"},
            {"/trips/{}", "/trips"},
        ),
        ({"main.py": '@app.get("/trips/{trip_id}")\ndef t(): ...'}, {"/trips/{}"}),
        (
            {
                "routes.py": 'router = APIRouter(prefix="/fares")\n@router.get("/{city}")\ndef f(): ...'
            },
            {"/fares/{}"},
        ),
        ({"app.py": "@bp.route('/payouts/<int:pid>')\ndef p(): ..."}, {"/payouts/{}"}),
        (
            {
                "main.go": 'http.HandleFunc("/quotes", h)\nr.Get("/zones/{id}", h)\ne.POST("/charges", h)'
            },
            {"/quotes", "/zones/{}", "/charges"},
        ),
        (
            {
                "openapi.yaml": "openapi: 3.0.0\npaths:\n  /drivers/{id}:\n    get: {}\n  /drivers:\n    post: {}\n"
            },
            {"/drivers/{}", "/drivers"},
        ),
    ],
)
def test_route_exposers(tmp_path: Path, files: dict[str, str], expected: set[str]) -> None:
    assert _routes(tmp_path, files) == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("const r = await fetch(`${process.env.TRIPS_SVC_URL}/trips/${id}`)", "/trips/{}"),
        ("axios.post(`${API}/payments/charge`, body)", "/payments/charge"),
        ('resp = requests.get(f"{BILLING_URL}/invoices/{invoice_id}")', "/invoices/{}"),
        ('r = httpx.post(BASE + "/payouts", json=p)', "/payouts"),
        ('res, err := http.Get(base + "/zones/" + id)', "/zones/{}"),
        ("fetch('/api/trips')", "/api/trips"),
        ("fetch('http://trips-svc:8000/trips/' + id)", "/trips/{}"),
    ],
)
def test_client_calls(tmp_path: Path, line: str, expected: str) -> None:
    name = (
        "client.go"
        if "http.Get" in line
        else "client.py"
        if "requests" in line or "httpx" in line
        else "client.ts"
    )
    assert _routes(tmp_path, {name: line}, side="consumes") == {expected}


@pytest.mark.parametrize(
    "line",
    [
        "fetch('https://api.stripe.com/v1/charges')",
        'requests.post("https://hooks.slack.com/services/x/y")',
        "fetch(url)",
        "fetch(`${base}`)",
    ],
)
def test_external_or_opaque_calls_are_ignored(tmp_path: Path, line: str) -> None:
    assert _routes(tmp_path, {"c.ts": line}, side="consumes") == set()


def _facts(repo_id: str, exposes=(), consumes=(), aliases=()) -> RepoFacts:
    def fact(value: str, hints: tuple[str, ...] = ()) -> Fact:
        ev = Evidence(repo=repo_id, file="f", line=1, snippet="s")
        return Fact(kind=FactKind.HTTP_ROUTE, value=value, evidence=(ev,), hints=hints)

    return RepoFacts(
        repo_id,
        repo_id,
        Contracts(
            exposes=tuple(fact(v) for v in exposes),
            consumes=tuple(fact(v, h) for v, h in consumes),
        ),
        aliases=(repo_id, *aliases),
    )


def _http(edges) -> dict[tuple[str, str], Confidence]:
    return {(e.source, e.target): e.confidence for e in edges if e.type is EdgeType.CALLS_HTTP}


def test_unique_exposer_is_inferred_and_a_naming_hint_makes_it_extracted() -> None:
    trips = _facts("trips-svc", exposes=["/trips/{}"])
    web = _facts("web", consumes=[("/trips/{}", ())])
    gateway = _facts("gateway", consumes=[("/trips/{}", ("TRIPS_SVC_URL",))])
    edges = _http(match_edges([trips, web, gateway]))
    assert edges[("web", "trips-svc")] is Confidence.INFERRED
    assert edges[("gateway", "trips-svc")] is Confidence.EXTRACTED


def test_shared_or_generic_routes_and_self_calls_make_no_confident_edge() -> None:
    a = _facts("a", exposes=["/health", "/orders"], consumes=[("/orders", ())])
    b = _facts("b", exposes=["/health", "/orders"])
    c = _facts("c", consumes=[("/health", ()), ("/orders", ())])
    edges = _http(match_edges([a, b, c]))
    assert ("a", "a") not in edges
    assert all(conf is Confidence.AMBIGUOUS for conf in edges.values())


def test_scan_links_a_gateway_to_the_service_it_calls(tmp_path: Path) -> None:
    make_repo(tmp_path, "trips-svc", {"app/main.py": '@app.get("/trips/{trip_id}")\ndef t(): ...'})
    make_repo(
        tmp_path,
        "gateway",
        {
            "src/trips.ts": "export const t = (id) => fetch(`${process.env.TRIPS_SVC_URL}/trips/${id}`)"
        },
    )
    edges = _http(scan_workspace(tmp_path).workspace.edges)
    assert edges == {("gateway", "trips-svc"): Confidence.EXTRACTED}


HOSTILE = {
    "template": "fetch(`" + "${a}" * 200_000 + "`)",
    "route": "app.get('/" + "a/" * 300_000 + "')",
    "decorator": '@app.get("' + "{" * 1_000_000,
    "many-calls": "fetch('/x') " * 80_000,
}


@pytest.mark.parametrize("name", sorted(HOSTILE))  # short ids: Windows caps env var length
def test_http_detector_is_linear(tmp_path: Path, name: str) -> None:
    text = HOSTILE[name]
    repo = make_repo(tmp_path, "svc")
    write(repo, "big.ts", text[:999_000])
    start = time.perf_counter()
    HttpDetector().run(ctx_for(tmp_path, repo))
    assert time.perf_counter() - start < 1.5
