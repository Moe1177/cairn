"""Stack labels for where a repo deploys (spec §25, §26), from the files that say so."""

from cairn.detectors.base import DetectorContext

_DEPLOY_FILES = frozenset(
    {
        "serverless.yml",
        "serverless.yaml",
        "samconfig.toml",
        "cdk.json",
        "railway.json",
        "railway.toml",
        "fly.toml",
    }
)
_SAM_TEMPLATES = ("template.yaml", "template.yml")
_CI_DIRS = frozenset({".github", ".gitlab", ".circleci"})
_RAILWAY_CI = ("railway up", "railwayapp/cli", "railway-deploy")
_FLY_CI = ("flyctl deploy", "fly deploy", "superfly/flyctl-actions")


def deploy_stack(ctx: DetectorContext) -> list[str]:
    names = {p.name.lower() for p in ctx.files(_deploy_file)}
    labels = []
    if "serverless.yml" in names or "serverless.yaml" in names:
        labels.append("serverless")
    if "samconfig.toml" in names or any(
        "AWS::Serverless" in (ctx.read(p) or "") for p in ctx.files(_sam_template)
    ):
        labels.append("aws-sam")
    if "cdk.json" in names:
        labels.append("aws-cdk")
    if any(name.endswith(".tf") for name in names):
        labels.append("terraform")
    if "railway.json" in names or "railway.toml" in names or _ci_runs(ctx, _RAILWAY_CI):
        labels.append("railway")
    if "fly.toml" in names or _ci_runs(ctx, _FLY_CI):
        labels.append("fly")
    return labels


def _ci_runs(ctx: DetectorContext, markers: tuple[str, ...]) -> bool:
    """Whether a CI workflow deploys with one of these commands (`railway up`)."""
    for path in ctx.files(_yaml):
        parts = path.relative_to(ctx.repo.root).parts
        if parts and parts[0] in _CI_DIRS and any(m in (ctx.read(path) or "") for m in markers):
            return True
    return False


def _yaml(name: str) -> bool:
    return name.lower().endswith((".yml", ".yaml"))


def _deploy_file(name: str) -> bool:
    lowered = name.lower()
    return lowered in _DEPLOY_FILES or lowered.endswith(".tf")


def _sam_template(name: str) -> bool:
    return name.lower() in _SAM_TEMPLATES
