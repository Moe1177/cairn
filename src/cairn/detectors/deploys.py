"""Deploy detector (spec §24): a repo whose compose, Kubernetes or Helm files run sibling images.

`image: weaveworksdemos/catalogue:0.3.5` in a deploy repo says that repo runs `catalogue`. Only
namespaced images count (`org/name`, optionally behind a registry); the fact is `org/name`, and
the matcher links it when `name` is exactly a sibling repo and the same org runs at least one
other sibling (so a lone `grafana/grafana` never links to a repo that happens to be called
grafana). Helm's `repository: org/name` counts only inside an `image:` block, and CI workflow
files (`.github/`) are skipped: a checkout's `repository: org/repo` deploys nothing.
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
    rf"""^(\s*)(?:-\s*)?(image|repository)\s*:\s*["']?"""
    rf"""((?:{_SEGMENT}(?::\d{{1,5}})?/)(?:{_SEGMENT}/){{0,6}})({_SEGMENT}?)"""
    r"""(?::[\w.-]{1,128}|@sha256:[0-9a-f]{6,64})?["']?\s*(?:#.*)?$"""
)
_IMAGE_BLOCK = re.compile(r"^(\s*)(?:-\s*)?image\s*:\s*(?:#.*)?$")  # `image:` with no value
_SKIPPED_DIRS = frozenset({".github", ".gitlab", ".circleci"})


class DeploysDetector:
    id = "deploys"

    def run(self, ctx: DetectorContext) -> DetectorResult:
        consumes: list[Fact] = []
        for path in ctx.files(_is_yaml):
            if _SKIPPED_DIRS & set(path.relative_to(ctx.repo.root).parts):
                continue
            text = ctx.read(path)
            if text and ("image" in text or "repository" in text):
                consumes += _scan(ctx, path, text)
        return DetectorResult(consumes=merge_facts(consumes))


def _scan(ctx: DetectorContext, path: Path, text: str) -> list[Fact]:
    facts: list[Fact] = []
    block_indent: int | None = None  # inside a Helm-style `image:` block at this indent
    for line_no, raw in enumerate(text.splitlines(), start=1):
        if len(facts) >= MAX_FACTS_PER_FILE:
            break
        line = raw[:_LINE_MAX]
        indent = len(line) - len(line.lstrip())
        if block_indent is not None and line.strip() and indent <= block_indent:
            block_indent = None
        opened = _IMAGE_BLOCK.match(line)
        if opened:
            block_indent = len(opened.group(1))
            continue
        if "image" not in line and "repository" not in line:
            continue
        match = _IMAGE.match(line)
        if not match or not match.group(4):
            continue
        if match.group(2) == "repository" and block_indent is None:
            continue
        org = match.group(3).rstrip("/").rsplit("/", 1)[-1].split(":", 1)[0].lower()
        value = f"{org}/{match.group(4).lower()}"
        evidence = (ctx.evidence(path, line_no, line),)
        facts.append(Fact(kind=FactKind.DEPLOYS_IMAGE, value=value, evidence=evidence))
    return facts


def _is_yaml(name: str) -> bool:
    return PurePosixPath(name.lower()).suffix in (".yml", ".yaml")
