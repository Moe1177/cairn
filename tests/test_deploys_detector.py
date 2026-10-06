"""Phase 4 Task 2: a deploy repo (compose, Kubernetes, Helm) that runs sibling repos' images."""

from pathlib import Path

from cairn.model.graph import EdgeType
from cairn.render.card import render_card
from cairn.render.index import render_index
from cairn.scan import scan_workspace
from tests.helpers import make_repo

COMPOSE = """services:
  front-end:
    image: weaveworksdemos/front-end:0.3.12
  catalogue:
    image: "weaveworksdemos/catalogue:0.3.5"
  catalogue-db:
    image: weaveworksdemos/catalogue-db:0.3.0
  carts-db:
    image: mongo:3.4
  edge:
    image: node:20
"""
K8S = """apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      containers:
      - name: carts
        image: registry.example.com:5000/weaveworksdemos/carts@sha256:0123abcd
"""
HELM = """frontend:
  image:
    repository: weaveworksdemos/user
    tag: 0.4.7
"""


def _ws(tmp_path: Path) -> Path:
    for name in ("front-end", "catalogue", "carts", "user"):
        make_repo(tmp_path, name, {"README.md": f"# {name}\n"})
    make_repo(
        tmp_path,
        "deploy",
        {
            "docker-compose/docker-compose.yml": COMPOSE,
            "kubernetes/carts-dep.yaml": K8S,
            "helm/values.yaml": HELM,
        },
    )
    return tmp_path


def _deploys(ws: Path) -> set[tuple[str, str]]:
    return {
        (e.source, e.target)
        for e in scan_workspace(ws).workspace.edges
        if e.type is EdgeType.DEPLOYS
    }


def test_a_deploy_repo_links_to_every_service_it_runs(tmp_path: Path) -> None:
    assert _deploys(_ws(tmp_path)) == {
        ("deploy", "front-end"),
        ("deploy", "catalogue"),
        ("deploy", "carts"),
        ("deploy", "user"),
    }


def test_cards_say_deploys_and_index_does_not_call_it_use(tmp_path: Path) -> None:
    workspace = scan_workspace(_ws(tmp_path)).workspace
    repo = workspace.repo("catalogue")
    assert repo is not None
    assert "deploys" in render_card(repo, workspace)
    assert "used by" not in render_index(workspace, {})


def test_hostile_image_lines_are_linear(tmp_path: Path) -> None:
    import time

    from cairn.detectors.deploys import DeploysDetector
    from tests.helpers import ctx_for
    from tests.timing import time_limit

    repo = make_repo(tmp_path, "deploy")
    line = "image: " + "a/" * 2000 + "b" * 100 + ":" * 3000
    (repo / "x.yaml").write_text((line + "\n") * 200, encoding="utf-8")
    start = time.perf_counter()
    DeploysDetector().run(ctx_for(tmp_path, repo))
    assert time.perf_counter() - start < time_limit(1.0)
