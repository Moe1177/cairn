"""0.6 final-review fixes: families vs splits and subtrees, manual relations, git trust behind
the memo, Mongoose's real naming, and the minors."""

import json
import subprocess
from pathlib import Path

import pytest

from cairn.detectors.database import DatabaseDetector
from cairn.detectors.lineage import LineageDetector
from cairn.detectors.mongo import mongoose_collection
from cairn.discover import git as git_module
from cairn.model.graph import Confidence, Edge, EdgeType, FactKind, Repo, Workspace
from cairn.render.index import render_index
from cairn.scan import scan_workspace
from tests.helpers import ctx_for, make_repo

DATA = Path(__file__).resolve().parent / "data" / "mongoose_pluralize_8.18.json"


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return done.stdout.strip()


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "-m", message)


def _repo(path: Path, files: dict[str, str]) -> Path:
    path.mkdir(parents=True)
    for rel, text in files.items():
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_text(text, encoding="utf-8")
    _git(path, "init", "-q")
    _commit(path, "first")
    return path


def _pairs(ws: Path) -> dict[tuple[frozenset, EdgeType], Edge]:
    return {
        (frozenset((e.source, e.target)), e.type): e for e in scan_workspace(ws).workspace.edges
    }


# -- Families: splits and subtrees are not copies; user relations always stand ---------------


def test_a_split_keeps_its_database_link_as_a_suggestion(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    _repo(
        ws / "monolith",
        {
            "db/schema.sql": "CREATE TABLE invoices (id int);\n",
            "app/billing.py": 'q = "SELECT * FROM invoices"\n',
        },
    )
    _git(ws, "clone", "-q", str(ws / "monolith"), "billing-svc")
    split = ws / "billing-svc"
    _git(split, "rm", "-q", "-r", "db")
    _commit(split, "split billing out")
    pairs = _pairs(ws)
    pair = frozenset(("monolith", "billing-svc"))
    assert (pair, EdgeType.MIRRORS) in pairs
    shared = pairs.get((pair, EdgeType.SHARES_DB))
    assert shared is not None and shared.confidence is Confidence.AMBIGUOUS  # demoted, not lost


def test_a_subtree_merge_is_not_a_copy(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    lib = _repo(ws / "x", {"x.py": "X = 1\n"})
    mono = _repo(ws / "mono", {"main.py": "print(1)\n"})
    _git(mono, "fetch", "-q", str(lib), "HEAD")
    _git(
        mono,
        "-c",
        "user.email=a@b",
        "-c",
        "user.name=a",
        "merge",
        "-q",
        "--allow-unrelated-histories",
        "-m",
        "add x",
        "FETCH_HEAD",
    )
    assert (frozenset(("mono", "x")), EdgeType.MIRRORS) not in _pairs(ws)


def test_a_declared_relation_between_copies_stands(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    _repo(ws / "app", {"README.md": "# app\n"})
    _git(ws, "clone", "-q", str(ws / "app"), "app-staging")
    (ws / ".cairn").mkdir()
    (ws / ".cairn" / "relations.yaml").write_text(
        "edges:\n  - {from: app, to: app-staging, type: shares_db, note: one database}\n",
        encoding="utf-8",
    )
    shared = _pairs(ws).get((frozenset(("app", "app-staging")), EdgeType.SHARES_DB))
    assert shared is not None and shared.confidence is not Confidence.AMBIGUOUS


def test_sha256_repositories_have_roots(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "--object-format=sha256")
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _commit(repo, "first")
    facts = LineageDetector().run(ctx_for(tmp_path, repo)).exposes
    assert len(facts) == 1 and len(facts[0].value) == 64


def test_a_repo_without_commits_scans(tmp_path: Path) -> None:
    repo = tmp_path / "empty"
    repo.mkdir()
    _git(repo, "init", "-q")
    assert scan_workspace(tmp_path).workspace.repo("empty") is not None


def test_a_big_family_stays_short_on_the_index() -> None:
    names = [f"registration-{year}" for year in range(2019, 2026)]
    repos = tuple(Repo(id=n, path=n) for n in names)
    edges = tuple(
        Edge(source=a, target=b, type=EdgeType.MIRRORS, confidence=Confidence.EXTRACTED, score=1)
        for i, a in enumerate(names)
        for b in names[i + 1 :]
    )
    text = render_index(
        Workspace(workspace_root="/w", generated_at="t", repos=repos, edges=edges), {}
    )
    line = next(line for line in text.splitlines() if line.startswith("- registration-2019"))
    assert line.endswith("copies: registration-2020, registration-2021 +4")


# -- Git trust behind the memo -----------------------------------------------------------------


def test_the_trust_warning_fires_even_when_the_memo_knows_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = tmp_path / "ws"
    _repo(ws / "app", {"README.md": "# app\n"})
    assert not [w for w in scan_workspace(ws).warnings if "safe.directory" in w]
    git_module.forget_git_memo()  # a later process: the memo comes from disk
    monkeypatch.setenv("GIT_TEST_ASSUME_DIFFERENT_OWNER", "1")
    warnings = [w for w in scan_workspace(ws).warnings if "safe.directory" in w]
    assert len(warnings) == 1 and "app" in warnings[0]


def test_the_trust_command_quotes_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = tmp_path / "my ws"
    _repo(ws / "my app", {"README.md": "# app\n"})
    monkeypatch.setenv("GIT_TEST_ASSUME_DIFFERENT_OWNER", "1")
    warning = next(w for w in scan_workspace(ws).warnings if "safe.directory" in w)
    assert "safe.directory '" in warning and "my app'" in warning


# -- Mongoose's own naming ---------------------------------------------------------------------


def test_collection_names_match_mongoose_exactly() -> None:
    expected = json.loads(DATA.read_text(encoding="utf-8"))
    wrong = {
        m: (mongoose_collection(m), c) for m, c in expected.items() if mongoose_collection(m) != c
    }
    assert not wrong


def _tables(tmp_path: Path, text: str) -> set[str]:
    repo = make_repo(tmp_path, "app", {"models/m.ts": text})
    result = DatabaseDetector().run(ctx_for(tmp_path, repo))
    return {f.value for f in (*result.exposes, *result.consumes) if f.kind is FactKind.DB_TABLE}


def test_a_schema_collection_option_names_the_collection(tmp_path: Path) -> None:
    text = (
        'import mongoose from "mongoose";\n'
        'const s = new mongoose.Schema({ at: Date }, { collection: "event_log" });\n'
        'export default mongoose.model("Event", s);\n'
    )
    assert _tables(tmp_path, text) == {"event_log"}


def test_multi_line_and_generic_models_are_read(tmp_path: Path) -> None:
    text = (
        'import mongoose, { Model } from "mongoose";\n'
        "export const User = mongoose.model<IUser>(\n"
        '  "User",\n'
        "  userSchema,\n"
        ");\n"
        'export const Team = mongoose.model<ITeam, Model<ITeam>>("Team", teamSchema);\n'
    )
    assert _tables(tmp_path, text) == {"users", "teams"}


def test_a_mongo_mention_in_a_comment_is_not_an_import(tmp_path: Path) -> None:
    text = (
        "// this used to live in mongodb\n"
        'const llm = registry.model("gpt-4o", options);\n'
        'const s = cache.collection("sessions");\n'
    )
    assert _tables(tmp_path, text) == set()
