"""Infra detector (spec §21.2): docker-compose `depends_on` between services built from repos.

Each compose service maps to a repo through its `build:` context (a workspace path) or its
`image:` name (matched to a repo alias later, by the matcher). A `depends_on` from S1 to S2 is
emitted as one fact, `<ref S1>=><ref S2>`, on the repo holding the compose file. Live, like
pathrefs: the workspace paths depend on where repos sit.
"""

from pathlib import Path, PurePosixPath

import yaml

from cairn.detectors.base import DetectorContext, DetectorResult, find_line, merge_facts
from cairn.detectors.database import MAX_FACTS_PER_FILE
from cairn.model.graph import Fact, FactKind

_COMPOSE_MAX = 256_000  # real compose files are small; anything bigger isn't worth parsing
_Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


class InfraDetector:
    id = "infra"

    def run(self, ctx: DetectorContext) -> DetectorResult:
        consumes: list[Fact] = []
        for path in ctx.files(_is_compose):
            text = ctx.read(path)
            if text and len(text) <= _COMPOSE_MAX:
                consumes += _compose_links(ctx, path, text)
        return DetectorResult(consumes=merge_facts(consumes))


def _is_compose(name: str) -> bool:
    lowered = name.lower()
    stem = PurePosixPath(lowered).stem
    return lowered.endswith((".yml", ".yaml")) and (
        stem.startswith("docker-compose") or stem.startswith("compose")
    )


def _compose_links(ctx: DetectorContext, path: Path, text: str) -> list[Fact]:
    try:
        data = yaml.load(text, Loader=_Loader)  # noqa: S506 - a safe loader
    except yaml.YAMLError:
        return []
    services = data.get("services") if isinstance(data, dict) else None
    if not isinstance(services, dict):
        return []
    refs = {name: _ref(ctx, path, spec) for name, spec in services.items() if isinstance(name, str)}
    facts: list[Fact] = []
    for name, spec in services.items():
        source = refs.get(name)
        if not source or not isinstance(spec, dict):
            continue
        for dependency in _depends_on(spec.get("depends_on")):
            target = refs.get(dependency)
            if target and target != source and len(facts) < MAX_FACTS_PER_FILE:
                line_no, line = find_line(text, dependency)
                evidence = (ctx.evidence(path, line_no, line),)
                facts.append(
                    Fact(
                        kind=FactKind.COMPOSE_SERVICE,
                        value=f"{source}=>{target}",
                        evidence=evidence,
                    )
                )
    return facts


def _depends_on(value: object) -> list[str]:
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    if isinstance(value, dict):
        return [k for k in value if isinstance(k, str)]
    return []


def _ref(ctx: DetectorContext, compose: Path, spec: object) -> str | None:
    """`path:<workspace path>` for a build context, `image:<name>` for an image, else None."""
    if not isinstance(spec, dict):
        return None
    build = spec.get("build")
    context = build.get("context") if isinstance(build, dict) else build
    if isinstance(context, str) and context.strip():
        try:
            target = (compose.parent / context.strip()).resolve()
            rel = target.relative_to(ctx.workspace_root.resolve()).as_posix()
        except (OSError, ValueError):
            return None
        return f"path:{rel}"
    image = spec.get("image")
    if isinstance(image, str) and image.strip():
        name = image.strip().split("@", 1)[0].rsplit("/", 1)[-1].split(":", 1)[0].lower()
        return f"image:{name}" if name else None
    return None
