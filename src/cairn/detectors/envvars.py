"""Env-vars detector (spec §21.3): which specific configuration names a repo reads.

Names come from `.env.example`-style templates (names only: a value is never read into a fact,
not even into an evidence snippet) and from code references. Framework prefixes such as
NEXT_PUBLIC_ are dropped, so a web app's NEXT_PUBLIC_TRIPS_SVC_URL matches a service's
TRIPS_SVC_URL; generic names (PORT, NODE_ENV, ...) are ignored.
"""

from pathlib import Path, PurePosixPath

from cairn.detectors.base import DetectorContext, DetectorResult, merge_facts
from cairn.detectors.database import MAX_FACTS_PER_FILE
from cairn.detectors.http_paths import GENERIC_ENV, env_names, template_env_names
from cairn.model.graph import Evidence, Fact, FactKind
from cairn.security.policy import ENV_TEMPLATES

_CODE_SUFFIXES = frozenset(
    {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py", ".go", ".rs", ".java", ".kt"}
)
_FRAMEWORK_PREFIXES = ("NEXT_PUBLIC_", "VITE_", "REACT_APP_", "EXPO_PUBLIC_", "PUBLIC_")


class EnvVarsDetector:
    id = "envvars"

    def run(self, ctx: DetectorContext) -> DetectorResult:
        consumes: list[Fact] = []
        for path in ctx.files(_wanted):
            text = ctx.read(path)
            if not text:
                continue
            template = path.name.lower() in ENV_TEMPLATES
            found = template_env_names(text) if template else env_names(text)
            for line_no, raw in found[:MAX_FACTS_PER_FILE]:
                name = specific_name(raw)
                if name:
                    # The line may hold a value (template) or a fallback default
                    # (`process.env.X || "dev-secret"`): keep where, never what. The name is
                    # the fact itself.
                    shown = ""
                    consumes.append(_fact(ctx, path, line_no, name, shown, template=template))
        return DetectorResult(consumes=merge_facts(consumes))


def specific_name(raw: str) -> str | None:
    """The name without framework prefixes, or None when it's too generic to mean anything."""
    name = raw
    for prefix in _FRAMEWORK_PREFIXES:
        if name.startswith(prefix):
            name = name[len(prefix) :]
            break
    if len(name) < 4 or name in GENERIC_ENV:
        return None
    return name


def _wanted(name: str) -> bool:
    lowered = name.lower()
    return lowered in ENV_TEMPLATES or PurePosixPath(lowered).suffix in _CODE_SUFFIXES


def _fact(
    ctx: DetectorContext, path: Path, line_no: int, name: str, shown: str, *, template: bool
) -> Fact:
    if template:
        evidence = Evidence(repo=ctx.repo.id, file=ctx.rel(path), line=line_no, snippet=shown)
    else:
        evidence = ctx.evidence(path, line_no, shown)
    return Fact(kind=FactKind.ENV_VAR_NAME, value=name, evidence=(evidence,))
