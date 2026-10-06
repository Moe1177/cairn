"""Phase 2e Task 4 (audit M2): adversarial 1 MB inputs parse in linear time."""

import time
from collections.abc import Callable
from pathlib import Path

import pytest

from cairn.detectors.database import DatabaseDetector
from cairn.detectors.identity import first_paragraph
from cairn.detectors.manifests import parse_go_mod
from cairn.security.redact import make_snippet, redact
from tests.helpers import ctx_for, make_repo
from tests.timing import time_limit

MB = 1_000_000


def _fast(fn: Callable[[], object], budget: float = 1.0) -> None:
    start = time.perf_counter()
    fn()
    assert time.perf_counter() - start < time_limit(budget)


ADVERSARIAL = {
    "userinfo": "x ://" + ":" * MB,
    "schemes": "x://" * (MB // 4),
    "keywords": "password=" * (MB // 9),
    "long-token": "a" * MB,
}


@pytest.mark.parametrize("name", sorted(ADVERSARIAL))
def test_redaction_is_linear(name: str) -> None:
    text = ADVERSARIAL[name]
    _fast(lambda: redact(text))
    _fast(lambda: make_snippet(text))
    _fast(lambda: first_paragraph("# t\n\n" + text))


def test_go_mod_require_block_is_linear() -> None:
    _fast(lambda: parse_go_mod("module x\n" + "require (\n" * (MB // 10)))


def test_go_mod_parsing_still_works() -> None:
    text = (
        "module example.com/a\n\nrequire (\n\tgithub.com/x/y v1.0.0 // indirect\n\tb.org/c v2\n)\n"
    )
    assert parse_go_mod(text) == ("example.com/a", ("github.com/x/y", "b.org/c"))


def test_prisma_models_are_linear_and_still_parsed(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, "app")
    schema = repo / "prisma" / "schema.prisma"
    schema.parent.mkdir()
    schema.write_text("model a {\n" * (MB // 10), encoding="utf-8")
    ctx = ctx_for(tmp_path, repo)
    _fast(lambda: DatabaseDetector().run(ctx), budget=1.0)
    # A hostile schema can't make cairn build an unbounded number of facts.
    schema.write_text("".join(f"model m{i} {{\n" for i in range(60_000)), encoding="utf-8")
    ctx = ctx_for(tmp_path, repo)  # a context is a snapshot: take a fresh one per rewrite
    _fast(lambda: DatabaseDetector().run(ctx), budget=1.0)
    assert len(DatabaseDetector().run(ctx).exposes) <= 2000
    schema.write_text(
        'model User {\n  id Int @id\n  @@map("app_users")\n}\n\nmodel Post {\n  id Int @id\n}\n',
        encoding="utf-8",
    )
    tables = {f.value for f in DatabaseDetector().run(ctx_for(tmp_path, repo)).exposes}
    assert {"app_users", "post"} <= {t.lower() for t in tables}


@pytest.mark.parametrize(
    ("name", "line"),
    [
        ("schema.sql", "CREATE TABLE t{i} (id int);"),
        ("queries.ts", "supabase.from('t{i}').select()"),
        ("queries.py", "q = 'SELECT * FROM t{i}'"),
    ],
)
def test_huge_files_build_a_bounded_number_of_facts(tmp_path: Path, name: str, line: str) -> None:
    repo = make_repo(tmp_path, "app")
    body = "\n".join(line.format(i=i) for i in range(30_000))
    (repo / name).write_text(body, encoding="utf-8")
    ctx = ctx_for(tmp_path, repo)
    _fast(lambda: DatabaseDetector().run(ctx), budget=1.5)
    result = DatabaseDetector().run(ctx)
    assert len(result.exposes) + len(result.consumes) <= 2000
