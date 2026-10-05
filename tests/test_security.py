from pathlib import Path

import pytest

from cairn.security.policy import is_forbidden
from cairn.security.redact import REDACTED, make_snippet, redact


@pytest.mark.parametrize(
    "name",
    [
        ".env",
        ".env.local",
        ".env.production",
        "prod.env",
        "server.pem",
        "tls.key",
        "id_rsa",
        ".npmrc",
        ".git-credentials",
        "credentials.json",
    ],
)
def test_secret_files_are_forbidden(name: str) -> None:
    assert is_forbidden(Path("repo") / name)


@pytest.mark.parametrize(
    "name",
    [".env.example", ".env.sample", ".env.template", "package.json", "schema.sql", "README.md"],
)
def test_normal_files_are_allowed(name: str) -> None:
    assert not is_forbidden(Path("repo") / name)


@pytest.mark.parametrize(
    "secret",
    [
        "sk_live_FAKEFAKEFAKEFAKE1234",
        "sk-proj-abcdefghijklmnop1234",
        "ghp_FAKEfakeFAKEfakeFAKEfake1234567890",
        "github_pat_11ABCDEFG0123456789_abcdef",
        "AKIAABCDEFGHIJKLMNOP",
        "xoxb-1234567890-abcdefghij",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
    ],
)
def test_known_secret_patterns_are_redacted(secret: str) -> None:
    out = redact(f"const key = '{secret}';")
    assert secret not in out
    assert REDACTED in out


def test_url_credentials_are_redacted() -> None:
    out = redact("postgres://admin:SuperSecretPw123@db.example.com/eats")
    assert "SuperSecretPw123" not in out
    assert out == f"postgres://{REDACTED}@db.example.com/eats"


def test_high_entropy_tokens_are_redacted() -> None:
    assert REDACTED in redact("token = 'a8F3kL9qZ2xV7mN4bR6tY1wE5uI0oP3s'")


def test_normal_code_is_untouched() -> None:
    for line in [
        "SELECT * FROM cook_profiles WHERE id = $1",
        "import { db } from '@/db'",
        "export const cook_fulfillment_windows_migration_name = 1",
        "src/components/very_long_component_name_v2_final.tsx",
    ]:
        assert redact(line) == line


def test_snippet_redacts_before_truncating() -> None:
    line = "x" * 150 + " ghp_FAKEfakeFAKEfakeFAKEfake1234567890"
    snippet = make_snippet(line)
    assert "ghp_" not in snippet
    assert len(snippet) <= 160


def test_snippet_truncates_long_lines() -> None:
    snippet = make_snippet("  " + "a " * 200)
    assert len(snippet) == 160
    assert snippet.endswith("…")


def test_url_credentials_with_empty_user_or_at_sign_are_redacted() -> None:
    # Final review: redis://:pw@host and passwords containing "@" leaked.
    assert redact("redis://:SuperSecretPw@cache:6379") == f"redis://{REDACTED}@cache:6379"
    out = redact("postgres://admin:p@ssW0rd@db.example.com/x")
    assert "ssW0rd" not in out and out.endswith("@db.example.com/x")
