"""Spec §26.3: Render Blueprints deploy sibling repos and link services that read each other."""

import time
from pathlib import Path

from cairn.detectors.identity import IdentityDetector
from cairn.detectors.platforms import deploy_stack
from cairn.detectors.render import RenderDetector, repo_name
from cairn.model.graph import Confidence, EdgeType
from cairn.render.card import render_card
from cairn.scan import scan_workspace
from tests.helpers import ctx_for, make_repo

BLUEPRINT = """services:
  - type: web
    name: storefront
    repo: https://github.com/acme/storefront
    envVars:
      - key: ORDERS
        fromService:
          type: pserv
          name: orders
          property: hostport
      - key: ORDERS_PORT
        fromService:
          type: pserv
          name: orders
          property: port
  - type: pserv
    name: orders
    repo: https://github.com/acme/orders-svc.git
    envVars:
      - key: SIGNING_KEY
        fromService:
          name: auth
          type: web
          envVarKey: SIGNING_KEY
      - key: DATABASE_URL
        fromDatabase:
          name: shop-db
          property: connectionString
  - type: worker
    name: mailer
    repo: https://github.com/elsewhere/mailer
"""


def _edges(ws: Path) -> set[tuple[str, str, EdgeType, Confidence]]:
    workspace = scan_workspace(ws).workspace
    return {(e.source, e.target, e.type, e.confidence) for e in workspace.edges}


def _workspace(tmp_path: Path) -> Path:
    make_repo(tmp_path, "infra", {"render.yaml": BLUEPRINT})
    make_repo(tmp_path, "storefront", {"package.json": '{"name": "storefront"}'})
    make_repo(tmp_path, "orders-svc", {"README.md": "# orders\n"})
    make_repo(tmp_path, "auth", {"render.yaml": "services:\n  - type: web\n    name: auth\n"})
    return tmp_path


def test_blueprints_deploy_sibling_repos_and_link_the_services_reading_each_other(
    tmp_path: Path,
) -> None:
    assert _edges(_workspace(tmp_path)) == {
        ("infra", "storefront", EdgeType.DEPLOYS, Confidence.EXTRACTED),
        ("infra", "orders-svc", EdgeType.DEPLOYS, Confidence.EXTRACTED),
        ("storefront", "orders-svc", EdgeType.CALLS_HTTP, Confidence.EXTRACTED),
        ("orders-svc", "auth", EdgeType.USES_RESOURCE, Confidence.EXTRACTED),
    }


def test_cards_say_what_render_links_mean(tmp_path: Path) -> None:
    workspace = scan_workspace(_workspace(tmp_path)).workspace
    storefront = workspace.repo("storefront")
    orders = workspace.repo("orders-svc")
    assert storefront is not None and orders is not None
    card = render_card(storefront, workspace)
    assert "calls orders.hostport, orders.port (render.yaml fromService)" in card
    assert "deploys it on Render (render.yaml)" in card
    assert "reads auth.env:SIGNING_KEY (render.yaml fromService)" in render_card(orders, workspace)


def test_a_service_two_blueprints_define_belongs_to_no_one(tmp_path: Path) -> None:
    worker = "services:\n  - type: worker\n    name: worker\n"
    reader = (
        "services:\n  - type: web\n    name: site\n    envVars:\n      - key: W\n"
        "        fromService:\n          type: worker\n          name: worker\n"
        "          property: host\n"
    )
    make_repo(tmp_path, "a", {"render.yaml": worker})
    make_repo(tmp_path, "b", {"render.yaml": worker})
    make_repo(tmp_path, "site", {"render.yaml": reader})
    assert not _edges(tmp_path)


def test_detector_facts_carry_the_code_repo_and_one_fact_per_reader(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "infra", {"render.yaml": BLUEPRINT})
    result = RenderDetector().run(ctx_for(tmp_path, repo))
    exposes = {(f.value, f.hints) for f in result.exposes}
    assert ("render:orders", ("repo:orders-svc",)) in exposes
    assert ("render:mailer", ("repo:mailer",)) in exposes
    consumes = {(f.value, f.hints) for f in result.consumes}
    assert consumes == {
        ("render:storefront>orders", ("property:hostport", "property:port")),
        ("render:orders>auth", ("property:env:SIGNING_KEY",)),
    }


def test_own_services_are_aliases_and_render_is_a_stack_label(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path,
        "shop",
        {
            "render.yaml": "services:\n  - type: web\n    name: acme-shop\n  - name: other\n"
            "    repo: https://github.com/acme/other\n"
        },
    )
    ctx = ctx_for(tmp_path, repo)
    aliases = IdentityDetector().run(ctx).aliases
    assert "acme-shop" in aliases and "other" not in aliases
    assert "render" in deploy_stack(ctx)


def test_repo_urls_name_their_repo() -> None:
    assert repo_name("https://github.com/acme/orders-svc.git") == "orders-svc"
    assert repo_name("https://gitlab.com/acme/group/Billing/") == "billing"
    assert repo_name("not a url with spaces") is None


def test_broken_or_hostile_blueprints_do_not_fail_or_crawl(tmp_path: Path) -> None:
    services = "".join(
        f"  - name: s{i}\n    envVars:\n"
        + "".join(f"      - fromService: {{name: s{j}, property: host}}\n" for j in range(10))
        for i in range(250)
    )
    repo = make_repo(
        tmp_path,
        "big",
        {"render.yaml": "services:\n" + services, "sub/render.yml": "services: [\n"},
    )
    start = time.perf_counter()
    RenderDetector().run(ctx_for(tmp_path, repo))
    assert time.perf_counter() - start < 3.0
