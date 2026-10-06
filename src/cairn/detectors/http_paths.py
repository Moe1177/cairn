"""Route templates and env-var names shared by the service detectors (spec §21.1, §21.3).

Everything here is line-based with bounded patterns: hostile files can't make it slow.
"""

import re

ROUTE_MAX = 300
PARAM = "{}"
GENERIC_ROUTES = frozenset(
    {"/", "/status", "/metrics", "/ping", "/version", "/login", "/logout", "/api", "/graphql"}
)
_PROBE_PREFIXES = ("health", "ready", "live")
_PARAM_SEGMENT = re.compile(r":\w+|\{[^/]{0,80}\}|\[[^/]{0,80}\]|<[^/]{0,80}>|.*\$\{.*")
_GROUP_SEGMENT = re.compile(r"\([^/]{0,80}\)")

_ENV_NAME = r"([A-Z][A-Z0-9_]{2,63})"
_ENV_REF = re.compile(
    rf"(?:process\.env|import\.meta\.env)\.{_ENV_NAME}\b"
    rf"|(?:process\.env|os\.environ)\[\s*['\"]{_ENV_NAME}['\"]"
    rf"|(?:os\.environ\.get|os\.getenv|os\.Getenv|env::var|System\.getenv)\(\s*['\"]{_ENV_NAME}['\"]"
)
_TEMPLATE_LINE = re.compile(r"\s*(?:export\s+)?([A-Z][A-Z0-9_]{1,63})\s*=")

# Names nearly every service sets: sharing one says nothing about a relationship.
GENERIC_ENV = frozenset(
    {
        "NODE_ENV",
        "PORT",
        "HOST",
        "HOSTNAME",
        "DEBUG",
        "LOG_LEVEL",
        "ENV",
        "ENVIRONMENT",
        "APP_ENV",
        "DATABASE_URL",
        "REDIS_URL",
        "TZ",
        "CI",
        "PATH",
        "HOME",
        "PWD",
        "USER",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "SECRET_KEY",
        "JWT_SECRET",
        "SENTRY_DSN",
        "PYTHONPATH",
    }
)


def normalize_route(raw: str) -> str | None:
    """`/trips/:id/` -> `/trips/{}`; None when `raw` isn't a usable absolute path."""
    path = raw.strip()
    if not path.startswith("/") or len(path) > ROUTE_MAX:
        return None
    path = path.split("?", 1)[0].split("#", 1)[0]
    segments: list[str] = []
    for segment in path.split("/"):
        if not segment or _GROUP_SEGMENT.fullmatch(segment):
            continue
        segments.append(PARAM if _PARAM_SEGMENT.fullmatch(segment) else segment.lower())
    return "/" + "/".join(segments)


def is_generic(template: str) -> bool:
    """Health checks, auth pages and all-parameter routes say nothing about who calls whom."""
    if template in GENERIC_ROUTES:
        return True
    segments = [s for s in template.split("/") if s]
    if all(s == PARAM for s in segments):
        return True
    return len(segments) == 1 and segments[0].startswith(_PROBE_PREFIXES)


def env_names(text: str) -> list[tuple[int, str]]:
    """(line, NAME) for env vars read in code (JS/TS, Python, Go, Rust, Java)."""
    found: list[tuple[int, str]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for match in _ENV_REF.finditer(line[:2000]):
            found.append((line_no, next(g for g in match.groups() if g)))
    return found


def template_env_names(text: str) -> list[tuple[int, str]]:
    """(line, NAME) from a `.env.example`-style template. Values are never returned."""
    found: list[tuple[int, str]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        match = _TEMPLATE_LINE.match(line)
        if match:
            found.append((line_no, match.group(1)))
    return found
