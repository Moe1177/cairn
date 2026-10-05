"""Phase 2e Task 3 (audit M1, L1): more secret shapes redacted, more credential files refused."""

from pathlib import Path

import pytest

from cairn.security.policy import is_forbidden
from cairn.security.redact import make_snippet, redact
from tests.helpers import ctx_for, make_repo

# (input line, the secret that must not survive)
LEAKS = [
    ("INSERT INTO users (email,password) VALUES ('admin@corp.io','Sup3rS3cret!')", "Sup3rS3cret!"),
    ("db.password='hunter2pass'", "hunter2pass"),
    ('{"password": "jsonPassw0rd"}', "jsonPassw0rd"),
    ("jdbc:postgresql://db:5432/app?user=app&password=s3cretJdbc", "s3cretJdbc"),
    ("Server=db;Database=app;User Id=sa;Password=S3cr3tNet;", "S3cr3tNet"),
    ("postgres://user:pa/ss@host/db", "pa/ss"),
    ("redis://:p@ssw0rd@cache:6379", "ssw0rd"),
    ("https://glpat-AbCdEfGhIjKlMnOpQrSt@gitlab.com/x.git", "glpat-AbCdEfGhIjKlMnOpQrSt"),
    ("//registry.npmjs.org/:_authToken=npm_A1b2C3d4E5f6G7h8I9j0", "npm_A1b2C3d4E5f6G7h8I9j0"),
    ("Authorization: Bearer abc123.def456.ghi789", "abc123.def456.ghi789"),
    ("SUPABASE_KEY sb_secret_N7UND0UgjKTVKUodkm0Hg", "sb_secret_N7UND0UgjKTVKUodkm0Hg"),
    ("stripe rk_live_51HabcDEFghi", "rk_live_51HabcDEFghi"),
    ("whsec_abcdef0123456789abcd signing", "whsec_abcdef0123456789abcd"),
    ("temp creds ASIAABCDEFGHIJKLMNOP", "ASIAABCDEFGHIJKLMNOP"),
    ("aws_secret_access_key=wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY", "wJalrXUtnFEMI"),
    ("API_KEY: 'abc-not-random-but-secret'", "abc-not-random-but-secret"),
]


@pytest.mark.parametrize(("line", "secret"), LEAKS)
def test_secret_shapes_are_redacted(line: str, secret: str) -> None:
    # audit M1
    assert secret not in redact(line)
    assert secret not in make_snippet(line)


@pytest.mark.parametrize(
    "line",
    [
        "import { Button } from '@acme/ui-kit';",
        "SELECT id, status FROM orders WHERE id = $1",
        "build: ../trips-svc",
        "https://github.com/acme/web.git",
    ],
)
def test_ordinary_lines_keep_their_shape(line: str) -> None:
    assert redact(line) == line


def test_sql_seed_rows_keep_location_but_no_snippet(tmp_path: Path) -> None:
    # audit M1: seed data in .sql files never becomes a snippet.
    repo = make_repo(tmp_path, "db")
    ctx = ctx_for(tmp_path, repo)
    seed = repo / "seed.sql"
    evidence = ctx.evidence(seed, 3, "INSERT INTO users VALUES (1, 'hunter2')")
    assert (evidence.file, evidence.line, evidence.snippet) == ("seed.sql", 3, "")
    schema = ctx.evidence(seed, 1, "CREATE TABLE users (id int)")
    assert schema.snippet == "CREATE TABLE users (id int)"


@pytest.mark.parametrize(
    "name",
    [
        ".envrc",
        ".pgpass",
        "pip.conf",
        "kubeconfig",
        ".htpasswd",
        "local.settings.json",
        "auth.json",
        "terraform.tfstate",
        "terraform.tfstate.backup",
        "secret.yaml",
        "secrets.prod.yaml",
        "values-secret.yml",
        "app-secrets.json",
        "appsettings.Production.json",
        "appsettings.json",
    ],
)
def test_more_credential_files_are_never_opened(name: str) -> None:
    # audit L1
    assert is_forbidden(Path("repo") / name)


def test_docker_config_is_never_opened() -> None:
    assert is_forbidden(Path("repo") / ".docker" / "config.json")
    assert not is_forbidden(Path("repo") / "config.json")


@pytest.mark.parametrize("name", [".env.example", "secretary.py", "tokens.ts", "README.md"])
def test_templates_and_ordinary_names_stay_readable(name: str) -> None:
    assert not is_forbidden(Path("repo") / name)
