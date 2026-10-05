"""Which files cairn must never open."""

from pathlib import Path

ENV_TEMPLATES = frozenset({".env.example", ".env.sample", ".env.template"})
SECRET_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx", ".jks", ".keystore"})
SECRET_NAMES = frozenset(
    {
        "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", ".npmrc", ".pypirc", ".netrc",
        ".git-credentials", "credentials", "credentials.json", "service-account.json",
    }
)


def is_forbidden(path: Path) -> bool:
    name = path.name.lower()
    if name in ENV_TEMPLATES:
        return False
    if name == ".env" or name.startswith(".env.") or name.endswith(".env"):
        return True
    return name in SECRET_NAMES or path.suffix.lower() in SECRET_SUFFIXES
