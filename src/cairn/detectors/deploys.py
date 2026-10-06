"""Deploy detector (spec §24): a repo whose compose, Kubernetes or Helm files run sibling images.

`image: weaveworksdemos/catalogue:0.3.5` in a deploy repo says that repo runs `catalogue`. Only
namespaced images count (`org/name`, optionally behind a registry), and only when the last path
segment is exactly a sibling repo's id or alias: `mongo:3.4`, `node:20` and `catalogue-db` never
link. Helm's `repository: org/name` counts the same way.
"""

import re
from pathlib import Path, PurePosixPath

from cairn.detectors.base import DetectorContext, DetectorResult, merge_facts
from cairn.detectors.database import MAX_FACTS_PER_FILE
from cairn.model.graph import Fact, FactKind

_LINE_MAX = 1000
_SEGMENT = r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"
# key: [quote] [registry[:port]/] org/.../name [:tag | @sha256:digest] [quote]
_IMAGE = re.compile(
    rf"""^\s*(?:-\s*)?(?:image|repository)\s*:\s*["']?"""
    rf"""((?:{_SEGMENT}(?::\d{{1,5}})?/)(?:{_SEGMENT}/){{0,6}})({_SEGMENT}?)"""
    r"""(?::[\w.-]{1,128}|@sha256:[0-9a-f]{6,64})?["']?\s*(?:#.*)?$"""
)


class DeploysDetector:
    id = "deploys"

    def run(self, ctx: DetectorContext) -> DetectorResult:
        consumes: list[Fact] = []
        for path in ctx.files(_is_yaml):
            text = ctx.read(path)
            if text and ("image" in text or "repository" in text):
                consumes += _scan(ctx, path, text)
        return DetectorResult(consumes=merge_facts(consumes))


def _scan(ctx: DetectorContext, path: Path, text: str) -> list[Fact]:
    facts: list[Fact] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        if len(facts) >= MAX_FACTS_PER_FILE:
            break
        line = raw[:_LINE_MAX]
        if "image" not in line and "repository" not in line:
            continue
        match = _IMAGE.match(line)
        if match and match.group(2):
            evidence = (ctx.evidence(path, line_no, line),)
            name = match.group(2).lower()
            facts.append(Fact(kind=FactKind.DEPLOYS_IMAGE, value=name, evidence=evidence))
    return facts


def _is_yaml(name: str) -> bool:
    return PurePosixPath(name.lower()).suffix in (".yml", ".yaml")
