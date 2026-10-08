"""Service-host detector (spec §24): calls addressed by a sibling's service name.

In Docker Compose and Kubernetes a service reaches another by its name: `http://catalogue`,
`http://carts:8080/carts`, `http://user.sock-shop.svc.cluster.local`, or a host-name constructor
(`new Hostname("payment")`). Each such host is a consumes fact; the matcher links it when the
name is exactly a sibling repo's id or alias. Hosts with a public domain (`api.github.com`),
`localhost`, IPs, comments and Python docstrings never count.

Platforms name private hosts explicitly (spec §26): Railway's `api.railway.internal` (with or
without a scheme) and its reference variables for another service's address
(`${{api.RAILWAY_PRIVATE_DOMAIN}}`, `${{api.URL}}`). Those forms are also read from proxy
configs (Caddyfile, `*.conf`) and env templates, where a bare `http://backend` is often an
upstream alias rather than a service, so only the explicit forms count there.
"""

import re
from pathlib import Path, PurePosixPath

from cairn.detectors.base import DetectorContext, DetectorResult, merge_facts
from cairn.detectors.database import MAX_FACTS_PER_FILE
from cairn.model.graph import Fact, FactKind

_LINE_MAX = 2000
_LABEL = r"([A-Za-z][A-Za-z0-9-]{0,62})"
# The first DNS label, then something that ends the host: a format placeholder, a port, a path,
# a closing quote, the end, or a Kubernetes service suffix. Any other dot means a real domain.
_URL = re.compile(
    rf"""\bhttps?://{_LABEL}(?=%s|\$\{{|\{{|:\d|/|["'`\s,;)]|$|"""
    r"""\.[a-z0-9-]{1,63}\.svc\b|\.svc\b|\.local\b)"""
)
# A literal handed to a host-name constructor: Hostname("payment"), ServiceHost("orders").
# A bare `host: "db"` (database, cache, Ansible, compose hostname, a Host header) says
# nothing about a call between services, so it never counts.
_PRIVATE_HOST = re.compile(rf"(?<![\w.-]){_LABEL}\.railway\.internal\b")
# ${{ api.RAILWAY_PRIVATE_DOMAIN }}: only variables that hold an address say "calls".
_REFERENCE = re.compile(rf"\$\{{\{{\s*{_LABEL}\.([A-Z][A-Z0-9_]{{0,80}})\s*\}}\}}")
_ADDRESS_VARS = re.compile(r"DOMAIN|URL|HOST|PORT|ADDR|ENDPOINT")
# Railway's database plugins and shared variables are not services of yours, and GitHub
# Actions writes its contexts the same way (`${{ secrets.API_URL }}`, `${{ env.HOST }}`).
_NOT_REFERENCED = frozenset(
    {"shared", "postgres", "postgresql", "mysql", "redis", "mongo", "mongodb", "minio"}
    | {"env", "vars", "secrets", "github", "steps", "needs", "matrix", "inputs", "job", "jobs"}
    | {"runner", "strategy"}
)
_HOST_LITERAL = re.compile(rf"""\b(?:Host[nN]ame|ServiceHost)\(\s*["']{_LABEL}["']""")
# A trailing comment: `//` not part of `://`, or `#` after whitespace in hash-comment files.
_SLASH_COMMENT = re.compile(r"(?<![:\w])//")
_HASH_COMMENT = re.compile(r"(?:^|\s)#")
_HASH_SUFFIXES = frozenset({".py", ".rb", ".yaml", ".yml", ".properties", ".toml"})
_NOT_SERVICES = frozenset({"localhost", "host", "example", "domain", "hostname", "server"})
_SUFFIXES = frozenset(
    {
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".py",
        ".go",
        ".java",
        ".kt",
        ".cs",
        ".rb",
        ".php",
        ".yaml",
        ".yml",
        ".properties",
        ".toml",
        ".json",
    }
)
# Files where only the explicit private forms count (see the module docstring).
_PRIVATE_ONLY_NAMES = frozenset({"caddyfile", ".env.example", ".env.sample", ".env.template"})
_PRIVATE_ONLY_SUFFIXES = frozenset({".conf"})
_COMMENT_PREFIXES = ("//", "#", "*", "/*", "<!--", "--")
_GATE = ("http", "host", "Host", "HOST", ".railway.internal", "${{")
_GATE_RE = re.compile("|".join(re.escape(key) for key in _GATE))


class HostsDetector:
    id = "hosts"

    def run(self, ctx: DetectorContext) -> DetectorResult:
        consumes: list[Fact] = []
        for path in ctx.files(_wanted):
            text = ctx.read(path)
            if text and _GATE_RE.search(text):
                consumes += _scan(ctx, path, text)
        return DetectorResult(consumes=merge_facts(consumes))


def _scan(ctx: DetectorContext, path: Path, text: str) -> list[Fact]:
    facts: list[Fact] = []
    suffix = path.suffix.lower()
    private_only = _private_only(path.name)
    hash_comments = suffix in _HASH_SUFFIXES or private_only
    in_docstring = False
    for line_no, raw in enumerate(text.splitlines(), start=1):
        if len(facts) >= MAX_FACTS_PER_FILE:
            break
        line = raw[:_LINE_MAX]
        if suffix == ".py":  # Python docstrings are prose, not calls
            quotes = line.count('"""') + line.count("'''")
            inside = in_docstring or quotes > 0
            if quotes % 2:
                in_docstring = not in_docstring
            if inside:
                continue
        if not _GATE_RE.search(line) or line.lstrip().startswith(_COMMENT_PREFIXES):
            continue
        code = _strip_comment(line, hash_comments=hash_comments)
        hosts = _private_hosts(code)
        if not private_only:
            hosts += [m.group(1) for m in _URL.finditer(code)]
            hosts += [m.group(1) for m in _HOST_LITERAL.finditer(code)]
        for host in dict.fromkeys(h.lower() for h in hosts):
            if host not in _NOT_SERVICES:
                evidence = (ctx.evidence(path, line_no, line),)
                facts.append(Fact(kind=FactKind.SERVICE_HOST, value=host, evidence=evidence))
    return facts


def _private_hosts(code: str) -> list[str]:
    hosts = [m.group(1) for m in _PRIVATE_HOST.finditer(code)] if ".railway." in code else []
    if "${{" in code:
        hosts += [
            m.group(1)
            for m in _REFERENCE.finditer(code)
            if _ADDRESS_VARS.search(m.group(2)) and m.group(1).lower() not in _NOT_REFERENCED
        ]
    return hosts


def _private_only(name: str) -> bool:
    lowered = name.lower()
    return lowered in _PRIVATE_ONLY_NAMES or PurePosixPath(lowered).suffix in _PRIVATE_ONLY_SUFFIXES


def _strip_comment(line: str, *, hash_comments: bool) -> str:
    cut = _SLASH_COMMENT.search(line)
    end = cut.start() if cut else len(line)
    if hash_comments:
        hashed = _HASH_COMMENT.search(line)
        if hashed:
            end = min(end, hashed.start())
    return line[:end]


def _wanted(name: str) -> bool:
    return PurePosixPath(name.lower()).suffix in _SUFFIXES or _private_only(name)
