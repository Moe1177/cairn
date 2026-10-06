"""Lineage detector: a repo's root commits, so copies of one app kept as separate repos (a
registration site cloned for each event, say) can be recognised as one family.

`git rev-list --max-parents=0 --first-parent HEAD` through cairn's hardened git (no hooks,
filters or fsmonitor). A fork or a clone keeps its original's first commit; an unrelated repo
built from a template (`create-next-app`, a GitHub template) doesn't. Following first parents
only, a history merged in later (a subtree, `--allow-unrelated-histories`) doesn't count: that
repo isn't a copy of the one it absorbed. A shallow clone's root is its cut-off, so shallow
clones simply don't find their family.
"""

import re

from cairn.detectors.base import DetectorContext, DetectorResult
from cairn.discover.git import git_text
from cairn.model.graph import Fact, FactKind

MAX_ROOTS = 5
_SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")  # SHA-1 or SHA-256 repositories


class LineageDetector:
    id = "lineage"

    def run(self, ctx: DetectorContext) -> DetectorResult:
        listing = (
            git_text(ctx.repo.root, ["rev-list", "--max-parents=0", "--first-parent", "HEAD"]) or ""
        )
        roots = sorted(line for line in listing.split() if _SHA.fullmatch(line))[:MAX_ROOTS]
        return DetectorResult(
            exposes=tuple(Fact(kind=FactKind.GIT_ROOT, value=sha) for sha in roots)
        )
