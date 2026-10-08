"""Spec §26: Railway's private network and reference variables name the services a repo calls."""

import time
from pathlib import Path

import pytest

from cairn.detectors.hosts import HostsDetector
from cairn.detectors.platforms import deploy_stack
from tests.helpers import ctx_for, make_repo


def _hosts(tmp_path: Path, files: dict[str, str]) -> set[str]:
    repo = make_repo(tmp_path, "caller", files)
    return {f.value for f in HostsDetector().run(ctx_for(tmp_path, repo)).consumes}


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("Caddyfile", "reverse_proxy http://orders.railway.internal:8080\n"),
        ("app.ts", 'const url = "http://orders.railway.internal:8080/v1";\n'),
        ("config.yaml", "redis_host: orders.railway.internal\n"),
        (".env.example", "ORDERS_URL=http://${{orders.RAILWAY_PRIVATE_DOMAIN}}:8080\n"),
        (".env.sample", "ORDERS=https://${{ orders.RAILWAY_PUBLIC_DOMAIN }}\n"),
        ("site.conf", "proxy_pass http://orders.railway.internal;\n"),
    ],
)
def test_private_hosts_and_address_references_name_the_service(
    tmp_path: Path, name: str, text: str
) -> None:
    assert _hosts(tmp_path, {name: text}) == {"orders"}


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("Caddyfile", "reverse_proxy http://backend:3000\n"),  # an upstream alias
        ("nginx.conf", "proxy_pass http://backend;\n"),
        (".env.example", "DATABASE_URL=${{Postgres.DATABASE_URL}}\n"),  # a database plugin
        (".env.example", "TOKEN=${{orders.SERVICE_TOKEN}}\n"),  # a secret, not an address
        (".env.example", "LOG=${{shared.LOG_URL}}\n"),  # shared variables
        ("deploy.yml", "API_URL: ${{ secrets.API_URL }}\nH: ${{ env.ORDERS_HOST }}\n"),
        ("Caddyfile", "# reverse_proxy http://orders.railway.internal\n"),  # a comment
        ("app.ts", 'const host = "db.orders.railway.internal.example.com";\n'),
    ],
)
def test_aliases_plugins_secrets_actions_contexts_and_comments_name_nothing(
    tmp_path: Path, name: str, text: str
) -> None:
    assert _hosts(tmp_path, {name: text}) == set()


def test_railway_stack_label_from_config_or_ci(tmp_path: Path) -> None:
    configured = make_repo(tmp_path, "api", {"railway.toml": "[deploy]\n"})
    deployed = make_repo(
        tmp_path,
        "web",
        {".github/workflows/deploy.yml": "steps:\n  - run: railway up --service web\n"},
    )
    plain = make_repo(tmp_path, "lib", {"README.md": "railway up\n"})
    assert "railway" in deploy_stack(ctx_for(tmp_path, configured))
    assert "railway" in deploy_stack(ctx_for(tmp_path, deployed))
    assert "railway" not in deploy_stack(ctx_for(tmp_path, plain))


def test_hostile_reference_lines_scan_in_linear_time(tmp_path: Path) -> None:
    line = "X=" + "${{" * 20_000 + "a." + "A" * 20_000 + "\n"
    hosts = "a" * 30_000 + ".railway.internal " + ".railway.internal" * 5_000 + "\n"
    start = time.perf_counter()
    _hosts(tmp_path, {".env.example": line + hosts})
    assert time.perf_counter() - start < 2.0
