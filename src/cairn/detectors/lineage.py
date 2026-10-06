"""Lineage detector: a repo's root commits, so copies of one app kept as separate repos (a
registration site cloned for each event, say) can be recognised as one family.

`git rev-list --max-parents=0 HEAD` through cairn's hardened git (no hooks, filters or
fsmonitor). A fork or a clone keeps its original's first commit; an unrelated repo built from a
template (`create-next-app`, a GitHub template) doesn't. At most a few roots are kept: merged
histories can have several.
"""

import re

from cairn.detectors.base import DetectorContext, DetectorResult
from cairn.discover.git import git_text
from cairn.model.graph import Fact, FactKind

MAX_ROOTS = 5
_SHA = re.compile(r"[0-9a-f]{40}")


class LineageDetector:
    id = "lineage"

    def run(self, ctx: DetectorContext) -> DetectorResult:
        listing = git_text(ctx.repo.root, ["rev-list", "--max-parents=0", "HEAD"]) or ""
        roots = [line for line in listing.split() if _SHA.fullmatch(line)][:MAX_ROOTS]
        return DetectorResult(
            exposes=tuple(Fact(kind=FactKind.GIT_ROOT, value=sha) for sha in sorted(roots))
        )
