"""Infra detector (spec §21.2): docker-compose `depends_on` between services built from repos.

Each compose service maps to a repo through its `build:` context (a workspace path) or its
`image:` name (matched to a repo alias later, by the matcher). A `depends_on` from S1 to S2 is
emitted as one fact, `<ref S1>=><ref S2>`, on the repo holding the compose file. Live, like
pathrefs: the workspace paths depend on where repos sit.
"""

from pathlib import Path, PurePosixPath

from cairn.detectors.base import DetectorContext, DetectorResult, find_line, merge_facts
from cairn.detectors.database import MAX_FACTS_PER_FILE
from cairn.model.graph import Fact, FactKind
from cairn.security.safe_yaml import load_yaml

_COMPOSE_MAX = 256_000  # real compose files are small; anything bigger isn't worth parsing
_MAX_SERVICES = 500
_MAX_DEPENDS = 200


class InfraDetector:
    id = "infra"

    def run(self, ctx: DetectorContext) -> DetectorResult:
        consumes: list[Fact] = []
        for path in ctx.files(is_compose_file):
            text = ctx.read(path)
            if text and len(text) <= _COMPOSE_MAX:
                consumes += _compose_links(ctx, path, text)
        return DetectorResult(consumes=merge_facts(consumes))


def is_compose_file(name: str) -> bool:
    lowered = name.lower()
    stem = PurePosixPath(lowered).stem
    return lowered.endswith((".yml", ".yaml")) and (
        stem.startswith("docker-compose") or stem.startswith("compose")
    )


def _compose_links(ctx: DetectorContext, path: Path, text: str) -> list[Fact]:
    data = load_yaml(text)
    services = data.get("services") if isinstance(data, dict) else None
    if not isinstance(services, dict):
        return []
    # Anchors can make a small file expand into a huge one: bound every loop (spec §20.1).
    entries = [(n, s) for n, s in list(services.items())[:_MAX_SERVICES] if isinstance(n, str)]
    refs = {name: _ref(ctx, path, spec) for name, spec in entries}
    facts: list[Fact] = []
    for name, spec in entries:
        source = refs.get(name)
        if not source or not isinstance(spec, dict):
            continue
        for dependency in dict.fromkeys(_depends_on(spec.get("depends_on"))[:_MAX_DEPENDS]):
            if len(facts) >= MAX_FACTS_PER_FILE:
                return facts
            target = refs.get(dependency)
            if target and target != source:
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
        if "://" in context or context.strip().startswith("git@"):
            return None  # a remote build context, not a sibling folder
        try:
            target = (compose.parent / context.strip()).resolve()
            rel = target.relative_to(ctx.workspace_root.resolve()).as_posix()
        except (OSError, ValueError):
            return None
        return f"path:{rel}"
    image = spec.get("image")
    if isinstance(image, str) and "/" in image and not image.startswith("library/"):
        # Only namespaced images (acme/api, ghcr.io/acme/api): `postgres:16` is Docker Hub's,
        # not a repo of yours that happens to be called postgres.
        name = image.strip().split("@", 1)[0].rsplit("/", 1)[-1].split(":", 1)[0].lower()
        return f"image:{name}" if name else None
    return None
