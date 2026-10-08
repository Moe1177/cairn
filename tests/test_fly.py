"""Spec §26.2: Fly.io apps are addressed by their fly.toml app name on the private network."""

import time
from pathlib import Path

import pytest

from cairn.detectors.hosts import HostsDetector
from cairn.detectors.identity import IdentityDetector
from cairn.detectors.platforms import deploy_stack
from tests.helpers import ctx_for, make_repo


def _hosts(tmp_path: Path, name: str, text: str) -> set[str]:
    repo = make_repo(tmp_path, "caller", {name: text})
    return {f.value for f in HostsDetector().run(ctx_for(tmp_path, repo)).consumes}


@pytest.mark.parametrize(
    "text",
    [
        'CORE = "http://orders.internal:8080"',
        'CORE = "iad.orders.internal:8080"',
        'CORE = "top2.nearest.of.orders.internal"',
        'CORE = "abc123.vm.orders.internal"',
        'CORE = "http://orders.flycast"',
        'CORE = "https://orders.fly.dev/api"',
    ],
)
def test_fly_hosts_name_the_app(tmp_path: Path, text: str) -> None:
    assert _hosts(tmp_path, "fly.toml", f"[env]\n  {text}\n") == {"orders"}


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("meta.py", 'URL = "http://metadata.google.internal/computeMetadata/v1/"\n'),
        ("tls.ts", 'const url = "https://host.docker.internal:8443";\n'),
        ("node.yaml", "node: ip-10-0-0-1.ec2.internal\n"),
        ("node.yaml", "node: ip-10-0-0-1.us-west-2.compute.internal\n"),
        ("meta.py", "from google.protobuf.internal import containers\n"),
        ("Main.java", "Object x = io.grpc.internal.Foo.create();\n"),
        ("db.yaml", "host: db.example.internal\n"),
        ("fly.toml", "# CORE = http://orders.internal:8080\n"),
    ],
)
def test_cloud_internal_names_code_paths_and_comments_name_no_app(
    tmp_path: Path, name: str, text: str
) -> None:
    assert _hosts(tmp_path, name, text) == set()


def test_the_fly_app_name_is_an_alias_of_its_repo(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "orders-service", {"fly.toml": 'app = "acme-orders"\n'})
    assert "acme-orders" in IdentityDetector().run(ctx_for(tmp_path, repo)).aliases


def test_fly_stack_label_from_config_or_ci(tmp_path: Path) -> None:
    configured = make_repo(tmp_path, "api", {"fly.toml": 'app = "api"\n'})
    deployed = make_repo(
        tmp_path,
        "web",
        {".github/workflows/fly.yml": "steps:\n  - run: flyctl deploy --remote-only\n"},
    )
    assert "fly" in deploy_stack(ctx_for(tmp_path, configured))
    assert "fly" in deploy_stack(ctx_for(tmp_path, deployed))


def test_hostile_fly_hosts_scan_in_linear_time(tmp_path: Path) -> None:
    text = "x = " + "a." * 30_000 + "internal " + "a-" * 30_000 + ".flycast\n"
    start = time.perf_counter()
    _hosts(tmp_path, "app.ts", text)
    assert time.perf_counter() - start < 2.0
