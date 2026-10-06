"""HTTP detector (spec §21.1): routes a repo serves, and the routes it calls on other services.

Line-based and bounded like every detector. Calls keep a *hint*: the env var or service host
their base URL comes from, which can name the service being called (`TRIPS_SVC_URL`).
"""

import re
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from cairn.detectors.base import DetectorContext, DetectorResult, merge_facts
from cairn.detectors.database import MAX_FACTS_PER_FILE
from cairn.detectors.http_paths import normalize_route
from cairn.model.graph import Fact, FactKind

_CODE_SUFFIXES = frozenset({".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py", ".go"})
_SPEC_SUFFIXES = frozenset({".yaml", ".yml", ".json"})
_NEXT_ROUTE_STEMS = frozenset({"route"})
_LINE_MAX = 2000
# How a route is served: by code, or only described by an OpenAPI file (which a frontend
# may keep for client generation without serving anything).
CODE_SOURCE = "source:code"
SPEC_SOURCE = "source:openapi"

_Q = r"""(?:'[^'\n]{0,500}'|"[^"\n]{0,500}"|`[^`\n]{0,500}`)"""
_BASE = r"""[\w.$\[\]'"]{1,100}\s*\+\s*"""

# -- routes a repo serves ------------------------------------------------------------------
_JS_ROUTE = re.compile(
    r"""\b(?:app|router|server|routes|fastify|hono|koa)\.(?:get|post|put|patch|delete|all|head"""
    r"""|options)\(\s*['"`](/[^'"`\s]{0,300})['"`]\s*,"""  # a handler follows the path
)
_PY_ROUTE = re.compile(
    r"""@\s*(\w{1,64})\.(?:get|post|put|patch|delete|route|api_route|websocket)\(\s*"""
    r"""['"](/[^'"\s]{0,300})['"]"""
)
_PY_PREFIX = re.compile(
    r"""\b(\w{1,64})\s*=\s*APIRouter\([^)\n]{0,200}?prefix\s*=\s*['"](/[^'"\s]{0,200})['"]"""
)
_GO_ROUTE = re.compile(
    r"""\.(?:HandleFunc|Handle|Get|Post|Put|Patch|Delete|GET|POST|PUT|PATCH|DELETE|Any)\(\s*"""
    r""""(/[^"\s]{0,300})"\s*,"""  # a handler follows the path; client .Get("/x") has none
)
_SPEC_PATH = re.compile(r"""\s{0,8}['"]?(/[^'"\s:]{0,300})['"]?\s*:""")

# -- calls a repo makes ----------------------------------------------------------------------
_JS_CALL = re.compile(
    rf"""\b(?:fetch|\$fetch|ofetch|ky|got|axios)(?:\.(?:get|post|put|patch|delete|head))?\(\s*"""
    rf"""((?:{_BASE})?{_Q})"""
)
_PY_CALL = re.compile(
    rf"""\b(?:requests|httpx|session|aiohttp|http_client)\.(?:get|post|put|patch|delete|head)\(\s*"""
    rf"""((?:{_BASE})?f?{_Q})"""
)
_GO_CALL = re.compile(
    r"""\bhttp\.(?:Get|Post|Head|NewRequest(?:WithContext)?)\(\s*(?:ctx\s*,\s*)?"""
    r"""(?:(?:"\w{1,10}"|http\.Method\w{1,10})\s*,\s*)?((?:[\w.]{1,100}\s*\+\s*)?"[^"\n]{0,500}")"""
)
_ENV_ASSIGN = re.compile(
    r"""\b(\w{1,64})\s*[:=]\s*(?:process\.env\.([A-Z][A-Z0-9_]{1,63})"""
    r"""|os\.(?:getenv|environ\.get)\(\s*['"]([A-Z][A-Z0-9_]{1,63})"""
    r"""|os\.environ\[\s*['"]([A-Z][A-Z0-9_]{1,63})|os\.Getenv\(\s*"([A-Z][A-Z0-9_]{1,63}))"""
)
_ENV_IN_EXPR = re.compile(r"""(?:process\.env|import\.meta\.env)\.([A-Z][A-Z0-9_]{1,63})""")
_UPPER_NAME = re.compile(r"[A-Z][A-Z0-9_]{1,63}")
_TEMPLATE_BASE = re.compile(r"""\$?\{([^{}]{1,120})\}""")

_LANGUAGE = {".py": "py", ".go": "go"}
_ROUTES = {"js": _JS_ROUTE, "py": _PY_ROUTE, "go": _GO_ROUTE}
_CALLS = {"js": _JS_CALL, "py": _PY_CALL, "go": _GO_CALL}


class HttpDetector:
    id = "http"

    def run(self, ctx: DetectorContext) -> DetectorResult:
        exposes: list[Fact] = []
        consumes: list[Fact] = []
        for path in ctx.files(_wanted):
            text = ctx.read(path)
            if not text:
                continue
            exposes += _file_route(ctx, path, text)
            if path.suffix.lower() in _SPEC_SUFFIXES:
                exposes += _spec_routes(ctx, path, text)
            elif path.suffix.lower() in _CODE_SUFFIXES:
                served, called = _code(ctx, path, text)
                exposes += served
                consumes += called
        return DetectorResult(exposes=merge_facts(exposes), consumes=merge_facts(consumes))


def _wanted(name: str) -> bool:
    lowered = name.lower()
    suffix = PurePosixPath(lowered).suffix
    if suffix in _CODE_SUFFIXES:
        return True
    return suffix in _SPEC_SUFFIXES and lowered.startswith(("openapi", "swagger"))


def _fact(
    ctx: DetectorContext,
    path: Path,
    line_no: int,
    line: str,
    raw: str,
    hint: str | None = None,
    *,
    source: str | None = None,
) -> list[Fact]:
    """A route fact. `hint` names a call's base URL; `source` says how a route is served."""
    template = normalize_route(raw)
    if template is None:
        return []
    evidence = (ctx.evidence(path, line_no, line),)
    hints = tuple(h for h in (hint, source) if h)
    return [Fact(kind=FactKind.HTTP_ROUTE, value=template, evidence=evidence, hints=hints)]


def _file_route(ctx: DetectorContext, path: Path, text: str) -> list[Fact]:
    """Next.js serves routes from the filesystem: app/**/route.ts and pages/api/**."""
    parts = PurePosixPath(ctx.rel(path)).parts
    stem = PurePosixPath(parts[-1]).stem.lower()
    if path.suffix.lower() not in _CODE_SUFFIXES:
        return []
    if stem in _NEXT_ROUTE_STEMS and "app" in parts[:-1]:
        start = len(parts) - 1 - parts[:-1][::-1].index("app")
        segments = [p for p in parts[start:-1] if not p.startswith(("@", "_"))]
    elif "pages" in parts[:-1] and parts[parts.index("pages") + 1 : parts.index("pages") + 2] == (
        "api",
    ):
        start = parts.index("pages") + 1
        segments = [*parts[start:-1], *([] if stem == "index" else [PurePosixPath(parts[-1]).stem])]
    else:
        return []
    route = "/" + "/".join(segments)
    first_line = text.splitlines()[0] if text.splitlines() else ""
    return _fact(ctx, path, 1, first_line, route, source=CODE_SOURCE)


def _spec_routes(ctx: DetectorContext, path: Path, text: str) -> list[Fact]:
    found: list[Fact] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        match = _SPEC_PATH.match(line[:_LINE_MAX])
        if match:
            found += _fact(ctx, path, line_no, line, match.group(1), source=SPEC_SOURCE)
        if len(found) >= MAX_FACTS_PER_FILE:
            break
    return found


def _code(ctx: DetectorContext, path: Path, text: str) -> tuple[list[Fact], list[Fact]]:
    served: list[Fact] = []
    called: list[Fact] = []
    lines = text.splitlines()
    env_of = _env_assignments(lines)
    prefixes = {
        m.group(1): m.group(2) for line in lines for m in _PY_PREFIX.finditer(line[:_LINE_MAX])
    }
    language = _LANGUAGE.get(path.suffix.lower(), "js")
    routes = _ROUTES[language]
    calls = _CALLS[language]
    for line_no, raw_line in enumerate(lines, start=1):
        if len(served) + len(called) >= MAX_FACTS_PER_FILE:
            break
        line = raw_line[:_LINE_MAX]
        for match in routes.finditer(line):
            route = match.group(match.lastindex or 1)
            if language == "py":
                route = prefixes.get(match.group(1), "") + route
            served += _fact(ctx, path, line_no, line, route, source=CODE_SOURCE)
        for match in calls.finditer(line):
            parsed = _call_target(match.group(1), line[match.end() :], env_of)
            if parsed is not None:
                called += _fact(ctx, path, line_no, line, parsed[0], parsed[1])
    return served, called


def _env_assignments(lines: list[str]) -> dict[str, str]:
    """`const API = process.env.TRIPS_URL` -> {"API": "TRIPS_URL"} (first assignment wins)."""
    found: dict[str, str] = {}
    for line in lines:
        for match in _ENV_ASSIGN.finditer(line[:_LINE_MAX]):
            name = next(g for g in match.groups()[1:] if g)
            found.setdefault(match.group(1), name)
    return found


def _call_target(arg: str, rest: str, env_of: dict[str, str]) -> tuple[str, str | None] | None:
    """(path, hint) from a client call's first argument, or None when it isn't a service path."""
    base, _, literal = arg.rpartition("+") if _is_concat(arg) else ("", "", arg)
    literal = literal.strip().removeprefix("f")
    text = literal[1:-1] if len(literal) >= 2 else ""
    hint = _hint(base.strip(), env_of) if base else None
    if text.startswith(("http://", "https://")):
        return _absolute(text, rest)
    if not text.startswith("/"):
        template_base = _TEMPLATE_BASE.match(text)
        if template_base is None:
            return None
        hint = hint or _hint(template_base.group(1).strip(), env_of)
        text = text[template_base.end() :]
        if not text.startswith("/"):
            return None
    if rest.lstrip().startswith("+") and text.endswith("/"):
        text += "{}"
    return text, hint


def _is_concat(arg: str) -> bool:
    return not arg.startswith(("'", '"', "`", "f'", 'f"'))


def _absolute(url: str, rest: str) -> tuple[str, str | None] | None:
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if not host or ("." in host and host != "127.0.0.1") or "{" in host or "$" in host:
        return None  # another company's API (api.stripe.com), or a host we can't read
    path = parts.path or "/"
    if rest.lstrip().startswith("+") and path.endswith("/"):
        path += "{}"
    return path, None if host in ("localhost", "127.0.0.1") else host


def _hint(expr: str, env_of: dict[str, str]) -> str | None:
    """The env var (or upper-case constant) a base URL expression names, if any."""
    env = _ENV_IN_EXPR.search(expr)
    if env:
        return env.group(1)
    name = expr.strip("{}$ ").split(".")[-1]
    if name in env_of:
        return env_of[name]
    return name if _UPPER_NAME.fullmatch(name) else None
