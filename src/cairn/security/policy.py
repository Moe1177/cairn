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


def never_open_globs() -> tuple[str, ...]:
    """is_forbidden() as gitignore-style globs (matched case-insensitively), for tools that pick
    files themselves, such as `git grep`: they must not open these files either. Wider than
    is_forbidden() where a glob can't say less (env templates are excluded too)."""
    globs = ["**/.env", "**/.env.*", "**/*.env", "**/*.tfstate*", "**/appsettings*.json"]
    globs += [f"**/{name}" for name in sorted(SECRET_NAMES)]
    globs += [f"**/*{suffix}" for suffix in sorted(SECRET_SUFFIXES)]
    globs += [f"**/*secret*{suffix}" for suffix in sorted(_DATA_SUFFIXES)]
    globs.append("**/.docker/config.json")
    return tuple(globs)
