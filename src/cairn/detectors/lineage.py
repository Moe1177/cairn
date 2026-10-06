"""Lineage detector: a repo's root commits, so copies of one app kept as separate repos (a
registration site cloned for each event, say) can be recognised as one family.

`git rev-list --max-parents=0 --first-parent HEAD` through cairn's hardened git (no hooks,
filters or fsmonitor). A fork or a clone keeps its original's first commit; an unrelated repo
built from a template (`create-next-app`, a GitHub template) doesn't. Following first parents
only, a history merged in later (a subtree, `--allow-unrelated-histories`) doesn't count: that
repo isn't a copy of the one it absorbed. A shallow clone's root is its cut-off, so shallow
clones simply don't find their family. The answer is remembered per HEAD (git memo).
"""

from cairn.detectors.base import DetectorContext, DetectorResult
from cairn.discover.git import root_commits
from cairn.model.graph import Fact, FactKind


class LineageDetector:
    id = "lineage"

    def run(self, ctx: DetectorContext) -> DetectorResult:
        # A timeout raises (GitTimeout): the scan records it, warns, and doesn't cache "no roots".
        roots = root_commits(ctx.repo.root)
        return DetectorResult(
            exposes=tuple(Fact(kind=FactKind.GIT_ROOT, value=sha) for sha in roots)
        )
