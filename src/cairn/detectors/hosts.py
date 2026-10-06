"""Service-host detector (spec §24): calls addressed by a sibling's service name.

In Docker Compose and Kubernetes a service reaches another by its name: `http://catalogue`,
`http://carts:8080/carts`, `http://user.sock-shop.svc.cluster.local`, or a host set from a literal
(`new Hostname("payment")`, `host = "orders"`). Each such host is a consumes fact; the matcher
links it when the name is exactly a sibling repo's id or alias. Hosts with a public domain
(`api.github.com`), `localhost` and IPs never count, and comment lines are skipped.
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
# A literal handed to something named for a host: Hostname("payment"), host = "orders".
_HOST_LITERAL = re.compile(rf"""(?i)\bhost\w{{0,30}}\s*(?:\(|=|:)\s*["']{_LABEL}["']""")
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


class HostsDetector:
    id = "hosts"

    def run(self, ctx: DetectorContext) -> DetectorResult:
        consumes: list[Fact] = []
        for path in ctx.files(_wanted):
            text = ctx.read(path)
            if text and any(key in text for key in _GATE):
                consumes += _scan(ctx, path, text)
        return DetectorResult(consumes=merge_facts(consumes))


def _scan(ctx: DetectorContext, path: Path, text: str) -> list[Fact]:
    facts: list[Fact] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        if len(facts) >= MAX_FACTS_PER_FILE:
            break
        line = raw[:_LINE_MAX]
        if not any(key in line for key in _GATE) or line.lstrip().startswith(_COMMENT_PREFIXES):
            continue
        hosts = [m.group(1) for m in _URL.finditer(line)]
        hosts += [m.group(1) for m in _HOST_LITERAL.finditer(line)]
        for host in dict.fromkeys(h.lower() for h in hosts):
            if host not in _NOT_SERVICES:
                evidence = (ctx.evidence(path, line_no, line),)
                facts.append(Fact(kind=FactKind.SERVICE_HOST, value=host, evidence=evidence))
    return facts


def _wanted(name: str) -> bool:
    return PurePosixPath(name.lower()).suffix in _SUFFIXES
