"""Which files cairn must never open."""

from pathlib import Path

ENV_TEMPLATES = frozenset({".env.example", ".env.sample", ".env.template"})
SECRET_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".tfvars"})
SECRET_NAMES = frozenset(
    {
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        ".npmrc",
        ".pypirc",
        ".netrc",
        ".git-credentials",
        "credentials",
        "credentials.json",
        "service-account.json",
        "secrets.yaml",
        "secrets.yml",
        "secrets.json",
        "secrets.toml",
        ".dev.vars",
        ".secrets",
        ".envrc",
        ".pgpass",
        ".htpasswd",
        "pip.conf",
        "kubeconfig",
        "local.settings.json",
        "auth.json",
    }
)
_DATA_SUFFIXES = frozenset({".yaml", ".yml", ".json", ".toml"})


def is_forbidden(path: Path) -> bool:
    name = path.name.lower()
    if name in ENV_TEMPLATES:
        return False
    if name == ".env" or name.startswith(".env.") or name.endswith(".env"):
        return True
    if name in SECRET_NAMES or path.suffix.lower() in SECRET_SUFFIXES:
        return True
    if ".tfstate" in name:  # terraform.tfstate, *.tfstate.backup: plaintext resource secrets
        return True
    if "secret" in name and path.suffix.lower() in _DATA_SUFFIXES:
        return True
    if name.startswith("appsettings") and name.endswith(".json"):  # .NET connection strings
        return True
    return name == "config.json" and path.parent.name.lower() == ".docker"
