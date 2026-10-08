"""Render Blueprints (spec §26.3): `render.yaml` names services, where their code lives, and
which services read each other's address.

Each service is a `platform_service` fact `render:<name>` the blueprint's repo exposes, with a
`repo:<name>` hint when the service is deployed from another repository (`repo:` URL). An env var
`fromService: {name: api, property: hostport}` read by `web` is a consumes fact `render:web>api`
(one per reader, so references never merge) with the property as a hint, so the matcher can link
the two services' repos,
wherever their code lives. `fromDatabase` and `fromGroup` name Render resources, not repos.
"""

import re
from pathlib import Path

from cairn.detectors.base import DetectorContext, DetectorResult, merge_facts
from cairn.detectors.database import MAX_FACTS_PER_FILE
from cairn.model.graph import Fact, FactKind
from cairn.security.safe_yaml import load_yaml
from cairn.security.text import valid_alias

BLUEPRINTS = ("render.yaml", "render.yml")
_TEXT_MAX = 512_000
_MAX_SERVICES = 500
_MAX_ENV = 500
_LINE_MAX = 2000


class RenderDetector:
    id = "render"

    def run(self, ctx: DetectorContext) -> DetectorResult:
        exposes: list[Fact] = []
        consumes: list[Fact] = []
        for path in ctx.files(is_blueprint):
            text = ctx.read(path)
            if text and len(text) <= _TEXT_MAX and "services" in text:
                found_exposes, found_consumes = _scan(ctx, path, text)
                exposes += found_exposes
                consumes += found_consumes
        return DetectorResult(exposes=merge_facts(exposes), consumes=merge_facts(consumes))


def is_blueprint(name: str) -> bool:
    return name.lower() in BLUEPRINTS


def services(text: str) -> list[dict]:
    """The blueprint's service entries that have a usable name."""
    data = load_yaml(text)
    entries = data.get("services") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return []
    return [
        s
        for s in entries[:_MAX_SERVICES]
        if isinstance(s, dict) and isinstance(s.get("name"), str) and valid_alias(s["name"].lower())
    ]


def own_service_names(text: str) -> list[str]:
    """Names of services deployed from the blueprint's own repo (no `repo:` elsewhere)."""
    return [s["name"].lower() for s in services(text) if not isinstance(s.get("repo"), str)]


def repo_name(url: str) -> str | None:
    """`https://github.com/acme/orders.git` -> `orders`."""
    name = url.strip().rstrip("/").rsplit("/", 1)[-1].removesuffix(".git").lower()
    return name if valid_alias(name) else None


_NAME_LINE = re.compile(r"""^(\s*)(?:-\s*)?name:\s*["']?([^"'#\s]{1,200})["']?\s*(?:#.*)?$""")


class _Names:
    """Every `name: x` line, indexed once: a service's definition is its shallowest such line
    (references sit deeper, inside another service's envVars), a reference the first after the
    reading service's definition."""

    def __init__(self, lines: list[str]) -> None:
        self._at: dict[str, list[tuple[int, int]]] = {}
        for number, line in enumerate(lines, start=1):
            match = _NAME_LINE.match(line[:_LINE_MAX])
            if match:
                entry = (number, len(match.group(1)))
                self._at.setdefault(match.group(2).lower(), []).append(entry)

    def definition(self, name: str) -> int:
        found = self._at.get(name.lower(), [])
        return min(found, key=lambda e: (e[1], e[0]))[0] if found else 1

    def reference(self, name: str, after: int) -> int:
        later = (n for n, _ in self._at.get(name.lower(), []) if n > after)
        return next(later, after)


def _scan(ctx: DetectorContext, path: Path, text: str) -> tuple[list[Fact], list[Fact]]:
    exposes: list[Fact] = []
    consumes: list[Fact] = []
    lines = text.splitlines() or [""]
    names = _Names(lines)
    for service in services(text):
        name = service["name"].lower()
        defined = names.definition(name)
        where = (ctx.evidence(path, defined, lines[defined - 1]),)
        url = service.get("repo")
        source = repo_name(url) if isinstance(url, str) else None
        hints = (f"repo:{source}",) if source else ()
        exposes.append(
            Fact(
                kind=FactKind.PLATFORM_SERVICE, value=f"render:{name}", evidence=where, hints=hints
            )
        )
        consumes += _references(ctx, path, lines, names, defined, name, service.get("envVars"))
        if len(exposes) + len(consumes) >= MAX_FACTS_PER_FILE:
            break
    return exposes, consumes


def _references(
    ctx: DetectorContext,
    path: Path,
    lines: list[str],
    names: "_Names",
    defined: int,
    reader: str,
    env_vars: object,
) -> list[Fact]:
    facts = []
    for env in env_vars[:_MAX_ENV] if isinstance(env_vars, list) else ():
        source = env.get("fromService") if isinstance(env, dict) else None
        if not isinstance(source, dict):
            continue
        target = source.get("name")
        if not isinstance(target, str) or not valid_alias(target.lower()):
            continue
        prop = source.get("property")
        key = source.get("envVarKey")
        what = prop if isinstance(prop, str) else f"env:{key}" if isinstance(key, str) else "ref"
        line_no = names.reference(target, after=defined)  # inside the reader's entry
        facts.append(
            Fact(
                kind=FactKind.PLATFORM_SERVICE,
                value=f"render:{reader}>{target.lower()}",
                evidence=(ctx.evidence(path, line_no, lines[line_no - 1]),),
                hints=(f"property:{what}",),
            )
        )
    return facts
