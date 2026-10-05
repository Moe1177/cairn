from pathlib import Path

from cairn.detectors.database import DatabaseDetector
from cairn.model.graph import FactKind
from tests.helpers import ctx_for, make_repo


def _tables(facts) -> list[str]:
    return [f.value for f in facts if f.kind is FactKind.DB_TABLE]


def test_sql_migrations_expose_tables(tmp_path: Path) -> None:
    sql = (
        'CREATE TABLE "cook_profiles" (id int);\n'
        "create table if not exists public.listings (id int);\n"
        'CREATE TABLE "public"."orders" (id int);\n'
        "INSERT INTO listings SELECT * FROM cook_profiles;\n"
    )
    repo = make_repo(tmp_path, "eats", {"db/migrations/0000.sql": sql})
    result = DatabaseDetector().run(ctx_for(tmp_path, repo))
    assert _tables(result.exposes) == ["cook_profiles", "listings", "orders"]
    assert _tables(result.consumes) == ["cook_profiles", "listings"]
    assert result.exposes[0].evidence[0].line == 1


def test_orm_declarations_expose_tables(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path,
        "web",
        {
            "db/schema.ts": 'export const dishes = pgTable("dishes", { id: serial("id") });\n',
            "prisma/schema.prisma": (
                'model Payment {\n  id Int @id\n  @@map("payments_ledger")\n}\n'
                "model Customer {\n  id Int @id\n}\n"
            ),
        },
    )
    result = DatabaseDetector().run(ctx_for(tmp_path, repo))
    assert _tables(result.exposes) == ["customer", "dishes", "payments_ledger"]


def test_code_references_consume_tables(tmp_path: Path) -> None:
    code = (
        "const a = sql`SELECT * FROM cook_profiles c JOIN listings l ON l.cook_id = c.id`;\n"
        'db.exec("UPDATE orders SET status = $1");\n'
        "const { data } = await supabase.from('dishes').select('*');\n"
    )
    repo = make_repo(
        tmp_path,
        "admin",
        {"lib/q.ts": code, "store.go": 'db.Exec("INSERT INTO payments_ledger VALUES ($1)")\n'},
    )
    result = DatabaseDetector().run(ctx_for(tmp_path, repo))
    assert _tables(result.consumes) == [
        "cook_profiles",
        "dishes",
        "listings",
        "orders",
        "payments_ledger",
    ]


def test_javascript_lookalikes_are_not_tables(tmp_path: Path) -> None:
    # Review Focus 3
    code = (
        'import React from "react";\n'
        "import { x } from './x';\n"
        'const b = Buffer.from("data");\n'
        "const c = Array.from(items);\n"
        "// UPDATE the cache later\n"
        "const q = 'SELECT 1 FROM (SELECT 2) sub';\n"
    )
    repo = make_repo(tmp_path, "app", {"src/index.ts": code})
    result = DatabaseDetector().run(ctx_for(tmp_path, repo))
    assert _tables(result.consumes) == []


def test_supabase_project_ref(tmp_path: Path) -> None:
    repo = make_repo(
        tmp_path,
        "app",
        {
            "supabase/config.toml": 'project_id = "abcd1234"\n',
            "config.toml": 'project_id = "nope"\n',
        },
    )
    result = DatabaseDetector().run(ctx_for(tmp_path, repo))
    refs = [f.value for f in result.consumes if f.kind is FactKind.DB_PROJECT_REF]
    assert refs == ["supabase:abcd1234"]


def test_test_code_and_fixtures_are_not_evidence(tmp_path: Path) -> None:
    # Found while dogfooding: cairn's own fixtures matched shopapp' tables.
    repo = make_repo(
        tmp_path,
        "tool",
        {
            "tests/fixtures/ws/schema.sql": "CREATE TABLE cook_profiles (id int);\n",
            "tests/test_db.py": 'Q = "SELECT * FROM cook_profiles"\n',
            "src/lib/q.test.ts": "const q = sql`SELECT * FROM orders`;\n",
            "src/lib/q_test.go": 'const q = "SELECT * FROM orders"\n',
            "src/lib/real.ts": "const q = sql`SELECT * FROM invoices`;\n",
        },
    )
    result = DatabaseDetector().run(ctx_for(tmp_path, repo))
    assert _tables(result.exposes) == []
    assert _tables(result.consumes) == ["invoices"]


def test_sql_keywords_and_system_catalogs_are_not_tables(tmp_path: Path) -> None:
    sql = (
        "CREATE TABLE orders (id int REFERENCES users(id) ON UPDATE NO ACTION);\n"
        "ALTER TABLE x ADD FOREIGN KEY (a) REFERENCES b(id) ON UPDATE CASCADE;\n"
        "SELECT conname FROM pg_constraint;\n"
        "SELECT * FROM sqlite_master;\n"
    )
    repo = make_repo(tmp_path, "db", {"migrations/1.sql": sql})
    result = DatabaseDetector().run(ctx_for(tmp_path, repo))
    assert _tables(result.consumes) == []
