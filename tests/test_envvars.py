"""Phase 2d Task 5: shared env vars as corroborating evidence (spec §21.3)."""

import json
from pathlib import Path

from cairn.detectors.envvars import EnvVarsDetector
from cairn.match.matcher import corroborate
from cairn.model.graph import Confidence, Edge, EdgeType, FactKind
from cairn.scan import scan_workspace
from tests.helpers import ctx_for, make_repo


def _edges(ws: Path) -> dict[tuple[frozenset[str], EdgeType], Confidence]:
    return {
        (frozenset((e.source, e.target)), e.type): e.confidence
        for e in scan_workspace(ws).workspace.edges
    }


def test_template_values_never_leave_the_file(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path,
        "svc",
        {
            ".env.example": "TRIPS_SVC_URL=http://internal-trips:8000\nPAYOUT_SIGNING_KEY=s3cr3t-value\n"
        },
    )
    result = EnvVarsDetector().run(ctx_for(tmp_path, repo))
    assert {f.value for f in result.consumes} == {"TRIPS_SVC_URL", "PAYOUT_SIGNING_KEY"}
    dumped = json.dumps([f.model_dump() for f in result.consumes])
    assert "internal-trips" not in dumped and "s3cr3t" not in dumped


def test_code_references_and_framework_prefixes(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path,
        "web",
        {
            "lib/api.ts": "const a = process.env.NEXT_PUBLIC_TRIPS_SVC_URL\nconst p = process.env.PORT"
        },
    )
    facts = EnvVarsDetector().run(ctx_for(tmp_path, repo)).consumes
    assert {f.value for f in facts} == {"TRIPS_SVC_URL"}
    assert all(f.kind is FactKind.ENV_VAR_NAME for f in facts)


def test_a_shared_env_var_alone_is_never_a_link(tmp_path: Path) -> None:
    # Dogfooding: unrelated projects all read STRIPE_SECRET_KEY / APP_URL. On its own a shared
    # name is only noise in `cairn status`; it exists solely to back up a real link.
    make_repo(tmp_path, "a", {".env.example": "PORT=1\nNODE_ENV=dev\nLEDGER_QUEUE=x\n"})
    make_repo(tmp_path, "b", {"main.py": "os.getenv('PORT')\nos.getenv('LEDGER_QUEUE')"})
    make_repo(tmp_path, "c", {"main.go": 'os.Getenv("NODE_ENV")'})
    assert not any(t is EdgeType.SHARES_ENV for _, t in _edges(tmp_path))


def test_another_link_upgrades_shares_env_to_inferred(tmp_path: Path) -> None:
    make_repo(
        tmp_path, "trips-svc", {"app.py": '@app.get("/trips/{id}")\nos.getenv("TRIPS_SIGNING_KEY")'}
    )
    make_repo(
        tmp_path,
        "gateway",
        {
            "t.ts": "fetch(`${process.env.TRIPS_SVC_URL}/trips/${id}`)\nprocess.env.TRIPS_SIGNING_KEY"
        },
    )
    edges = _edges(tmp_path)
    assert edges[(frozenset({"gateway", "trips-svc"}), EdgeType.SHARES_ENV)] is Confidence.INFERRED


def test_shares_env_never_upgrades_other_edges() -> None:
    db = Edge(
        source="a", target="b", type=EdgeType.SHARES_DB, confidence=Confidence.AMBIGUOUS, score=0.2
    )
    env = Edge(
        source="a", target="b", type=EdgeType.SHARES_ENV, confidence=Confidence.INFERRED, score=0.6
    )
    upgraded = {e.type: e.confidence for e in corroborate([db, env])}
    assert upgraded[EdgeType.SHARES_DB] is Confidence.AMBIGUOUS


def test_names_most_repos_share_are_ignored(tmp_path: Path) -> None:
    for name in ("a", "b", "c", "d", "e"):
        make_repo(tmp_path, name, {"m.py": "os.getenv('COMPANY_REGION_CODE')"})
    assert not any(t is EdgeType.SHARES_ENV for _, t in _edges(tmp_path))
