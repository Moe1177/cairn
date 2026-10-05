import json
from pathlib import Path

from cairn.detectors.packages import PackagesDetector
from tests.helpers import ctx_for, make_repo


def _values(facts) -> list[str]:
    return [f.value for f in facts]


def test_npm_exposes_and_consumes_with_evidence(tmp_path: Path) -> None:
    pkg = json.dumps(
        {"name": "@eats/ui", "dependencies": {"react": "19"}, "devDependencies": {"vitest": "2"}},
        indent=2,
    )
    repo = make_repo(tmp_path, "shared-ui", {"package.json": pkg})
    result = PackagesDetector().run(ctx_for(tmp_path, repo))
    assert _values(result.exposes) == ["npm:@eats/ui"]
    assert _values(result.consumes) == ["npm:react", "npm:vitest"]
    react = result.consumes[0].evidence[0]
    assert react.file == "package.json" and '"react"' in react.snippet


def test_python_names_are_normalized(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path,
        "orders-svc",
        {
            "pyproject.toml": '[project]\nname = "Orders_Svc"\ndependencies = ["Shopverse_Common>=0.1"]\n',
            "requirements.txt": "uvicorn==0.30\n",
        },
    )
    result = PackagesDetector().run(ctx_for(tmp_path, repo))
    assert _values(result.exposes) == ["pypi:orders-svc"]
    assert _values(result.consumes) == ["pypi:shopverse-common", "pypi:uvicorn"]


def test_go_and_cargo(tmp_path: Path) -> None:
    go = make_repo(
        tmp_path,
        "payments",
        {"go.mod": "module github.com/acme/payments\nrequire github.com/acme/money v0.1.0\n"},
    )
    rs = make_repo(
        tmp_path,
        "ledger",
        {"Cargo.toml": '[package]\nname = "ledger"\n[dependencies]\nserde = "1"\n'},
    )
    go_result = PackagesDetector().run(ctx_for(tmp_path, go))
    assert _values(go_result.exposes) == ["go:github.com/acme/payments"]
    assert _values(go_result.consumes) == ["go:github.com/acme/money"]
    rs_result = PackagesDetector().run(ctx_for(tmp_path, rs))
    assert _values(rs_result.exposes) == ["cargo:ledger"]
    assert _values(rs_result.consumes) == ["cargo:serde"]


def test_malformed_manifests_do_not_crash(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path,
        "broken",
        {"package.json": "{not json", "pyproject.toml": "[[[", "Cargo.toml": "x = "},
    )
    result = PackagesDetector().run(ctx_for(tmp_path, repo))
    assert result.exposes == () and result.consumes == ()
