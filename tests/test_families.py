"""0.6 Task 1: repo families: copies of one app kept as separate repos (shared history or name)."""

import subprocess
from pathlib import Path

from cairn.model.graph import Confidence, EdgeType
from cairn.render.card import render_card
from cairn.render.index import render_index
from cairn.scan import scan_workspace
from tests.helpers import make_repo


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "-m", message)


def _family(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    original = ws / "registration-website"
    original.mkdir(parents=True)
    (original / "README.md").write_text("# registration\n", encoding="utf-8")
    _git(original, "init", "-q")
    _commit(original, "first")
    _git(ws, "clone", "-q", str(original), "registration-website-2026")
    copy = ws / "registration-website-2026"
    (copy / "theme.css").write_text("body {}\n", encoding="utf-8")
    _commit(copy, "2026 theme")
    other = ws / "discord-bot"
    other.mkdir()
    (other / "bot.py").write_text("print(1)\n", encoding="utf-8")
    _git(other, "init", "-q")
    _commit(other, "bot")
    return ws


def _mirrors(ws: Path) -> list:
    return [e for e in scan_workspace(ws).workspace.edges if e.type is EdgeType.MIRRORS]


def test_repos_sharing_a_first_commit_are_one_family(tmp_path: Path) -> None:
    edges = _mirrors(_family(tmp_path))
    assert len(edges) == 1
    edge = edges[0]
    assert {edge.source, edge.target} == {"registration-website", "registration-website-2026"}
    assert edge.confidence is Confidence.EXTRACTED
    assert any(s.startswith("root:") for s in edge.signals)


def test_the_same_package_name_suggests_a_copy(tmp_path: Path) -> None:
    for name in ("admin", "admin-2026"):
        make_repo(tmp_path, name, {"package.json": '{"name": "next-app-test"}'})
    edges = _mirrors(tmp_path)
    assert len(edges) == 1 and edges[0].confidence is Confidence.AMBIGUOUS  # a suggestion


def test_a_name_shared_by_many_repos_is_too_generic(tmp_path: Path) -> None:
    for i in range(4):
        make_repo(tmp_path, f"app{i}", {"package.json": '{"name": "my-app"}'})
    assert _mirrors(tmp_path) == []


def test_cards_and_index_name_the_copies(tmp_path: Path) -> None:
    ws = _family(tmp_path)
    workspace = scan_workspace(ws).workspace
    repo = workspace.repo("registration-website")
    assert repo is not None
    card = render_card(repo, workspace)
    assert "copy of the same app" in card and "registration-website-2026" in card
    line = next(
        line
        for line in render_index(workspace, {}).splitlines()
        if line.startswith("- registration-website:")
    )
    assert "copies: registration-website-2026" in line


def test_copies_share_a_schema_not_a_database(tmp_path: Path) -> None:
    """Per-event copies define the same models because they're copies: that overlap is weak
    evidence of a shared database, so the link between them is only a suggestion."""
    ws = tmp_path / "ws"
    original = ws / "registration"
    (original / "models").mkdir(parents=True)
    (original / "models" / "qr.ts").write_text(
        'import mongoose from "mongoose";\n'
        'export const Qr = mongoose.model("QrCodeMapping", qrSchema);\n',
        encoding="utf-8",
    )
    _git(original, "init", "-q")
    _commit(original, "first")
    _git(ws, "clone", "-q", str(original), "registration-2026")
    checkin = ws / "checkin"
    (checkin / "scripts").mkdir(parents=True)
    (checkin / "scripts" / "qr.ts").write_text(
        'import { MongoClient } from "mongodb";\nconst qr = db.collection("qrcodemappings");\n',
        encoding="utf-8",
    )
    _git(checkin, "init", "-q")
    _commit(checkin, "checkin")
    edges = scan_workspace(ws).workspace.edges
    pairs = {(frozenset((e.source, e.target)), e.type) for e in edges}
    copies = frozenset(("registration", "registration-2026"))
    assert (copies, EdgeType.MIRRORS) in pairs
    confident = {
        (frozenset((e.source, e.target)), e.type)
        for e in edges
        if e.confidence.rank >= Confidence.INFERRED.rank
    }
    assert (copies, EdgeType.SHARES_DB) not in confident
    assert (copies, EdgeType.SHARES_ENV) not in confident
    assert (frozenset(("checkin", "registration")), EdgeType.SHARES_DB) in pairs
