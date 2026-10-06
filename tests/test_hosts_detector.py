"""Phase 4 Task 1: service-DNS hostnames that name a sibling repo (Sock Shop's coupling style)."""

import time
from pathlib import Path

from cairn.detectors.hosts import HostsDetector
from cairn.model.graph import EdgeType, FactKind
from cairn.scan import scan_workspace
from tests.helpers import ctx_for, make_repo
from tests.timing import time_limit

ENDPOINTS_JS = """module.exports = {
  catalogueUrl:  util.format("http://catalogue%s", domain),
  cartsUrl:      util.format("http://carts%s/carts", domain),
  ordersUrl:     util.format("http://orders%s", domain),
  customersUrl:  `http://user${domain}/customers`,
  loginUrl:      "http://user:8080/login",
  selfUrl:       "http://front-end/index.html",
};
"""
ORDERS_JAVA = """class OrdersConfigurationProperties {
    public URI getPaymentUri() {
        return new ServiceUri(new Hostname("payment"), new Domain(domain), "/paymentAuth").toUri();
    }
    public URI getShippingUri() {
        return new ServiceUri(new Hostname("shipping"), new Domain(domain), "/shipping").toUri();
    }
}
"""
LOOKALIKES = """// curl http://catalogue/catalogue to try it
const docs = "http://localhost:8080/carts";
const gh = "http://api.github.com/repos";
const host = "127.0.0.1";
"""


def _workspace(tmp_path: Path) -> Path:
    for name in ("catalogue", "carts", "orders", "user", "payment", "shipping", "api"):
        make_repo(tmp_path, name, {"README.md": f"# {name}\n"})
    make_repo(tmp_path, "front-end", {"api/endpoints.js": ENDPOINTS_JS})
    make_repo(tmp_path, "orders-svc-config", {"src/Config.java": ORDERS_JAVA})
    make_repo(tmp_path, "noise", {"src/app.js": LOOKALIKES})
    return tmp_path


def _links(ws: Path) -> set[tuple[str, str]]:
    edges = scan_workspace(ws).workspace.edges
    return {(e.source, e.target) for e in edges if e.type is EdgeType.CALLS_HTTP}


def test_service_dns_urls_and_host_literals_link_repos(tmp_path: Path) -> None:
    links = _links(_workspace(tmp_path))
    assert {
        ("front-end", "catalogue"),
        ("front-end", "carts"),
        ("front-end", "orders"),
        ("front-end", "user"),
        ("orders-svc-config", "payment"),
        ("orders-svc-config", "shipping"),
    } <= links


def test_lookalikes_never_link(tmp_path: Path) -> None:
    links = _links(_workspace(tmp_path))
    assert not {link for link in links if link[0] == "noise"}, links
    assert ("front-end", "front-end") not in links


def test_kubernetes_service_names_count(tmp_path: Path) -> None:
    make_repo(tmp_path, "catalogue", {"README.md": "# c\n"})
    make_repo(
        tmp_path,
        "web",
        {"config.yaml": "catalogue: http://catalogue.sock-shop.svc.cluster.local:80/\n"},
    )
    assert ("web", "catalogue") in _links(tmp_path)


def test_the_link_cites_the_line(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    edge = next(
        e
        for e in scan_workspace(ws).workspace.edges
        if (e.source, e.target) == ("front-end", "carts") and e.type is EdgeType.CALLS_HTTP
    )
    assert "host:carts" in edge.signals
    assert edge.evidence[0].file == "api/endpoints.js" and edge.evidence[0].line == 3


def test_hostile_input_is_linear(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "app")
    (repo / "big.js").write_text(
        ("http://" * 50_000) + ("host = '" * 50_000) + "\n", encoding="utf-8"
    )
    ctx = ctx_for(tmp_path, repo)
    start = time.perf_counter()
    result = HostsDetector().run(ctx)
    assert time.perf_counter() - start < time_limit(1.0)
    assert all(f.kind is FactKind.SERVICE_HOST for f in result.consumes)
