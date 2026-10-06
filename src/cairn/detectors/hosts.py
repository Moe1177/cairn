"""Service-host detector (spec §24): calls addressed by a sibling's service name.

In Docker Compose and Kubernetes a service reaches another by its name: `http://catalogue`,
`http://carts:8080/carts`, `http://user.sock-shop.svc.cluster.local`, or a host-name constructor
(`new Hostname("payment")`). Each such host is a consumes fact; the matcher links it when the
name is exactly a sibling repo's id or alias. Hosts with a public domain (`api.github.com`),
`localhost`, IPs, comments and Python docstrings never count.
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
_COMMENT_PREFIXES = ("//", "#", "*", "/*", "<!--", "--")
_GATE = ("http", "host", "Host", "HOST")
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
        code = _strip_comment(line, hash_comments=suffix in _HASH_SUFFIXES)
        hosts = [m.group(1) for m in _URL.finditer(code)]
        hosts += [m.group(1) for m in _HOST_LITERAL.finditer(code)]
        for host in dict.fromkeys(h.lower() for h in hosts):
            if host not in _NOT_SERVICES:
                evidence = (ctx.evidence(path, line_no, line),)
                facts.append(Fact(kind=FactKind.SERVICE_HOST, value=host, evidence=evidence))
    return facts


def _strip_comment(line: str, *, hash_comments: bool) -> str:
    cut = _SLASH_COMMENT.search(line)
    end = cut.start() if cut else len(line)
    if hash_comments:
        hashed = _HASH_COMMENT.search(line)
        if hashed:
            end = min(end, hashed.start())
    return line[:end]


def _wanted(name: str) -> bool:
    return PurePosixPath(name.lower()).suffix in _SUFFIXES
