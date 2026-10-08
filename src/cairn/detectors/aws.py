"""AWS detector (spec §25): which repo creates each AWS resource, and which repos use it.

A repo *exposes* `cloud_resource` facts for what its IaC creates (Terraform, CloudFormation/SAM,
Serverless Framework, CDK) and *consumes* them for what it points at: ARNs, queue URLs, SSM
lookups, CloudFormation imports, Terraform data sources, SDK calls and env vars naming a
resource. EventBridge sources become topic facts, so publisher -> subscriber links come from
the pub/sub matcher. Every name is reduced by aws_names so templates and literals compare.
"""

import re
from pathlib import PurePosixPath

from cairn.detectors import aws_code, aws_templates, aws_terraform
from cairn.detectors.aws_names import Expand, Found, env_references, line_references, value
from cairn.detectors.base import DetectorContext, DetectorResult, merge_facts
from cairn.detectors.database import MAX_FACTS_PER_FILE
from cairn.model.graph import Fact, FactKind

_TEXT_MAX = 1_000_000
_LINE_MAX = 2000
_CODE = frozenset({".ts", ".js", ".mjs", ".cjs", ".py", ".go", ".java", ".kt", ".cs"})
_DATA = frozenset({".yml", ".yaml", ".json"})
_SKIPPED = ("lock.json", ".d.ts", ".min.js", "package.json")
_COMMENT = ("#", "//", "/*", "*", "--")
# Any of these somewhere in a file, or it can't mention an AWS resource we'd read.
_GATE = (
    "arn:aws",
    "amazonaws.com",
    "AWS::",
    "aws_",
    "resolve:ssm",
    "${ssm",
    "${cf",
    "service:",
    "aws-cdk",
    "@aws-cdk",
    "aws_cdk",
    "awscdk",
    "@aws-sdk",
    "aws-sdk",
    "boto3",
    "aws-sdk-go",
    "TABLE",
    "QUEUE",
    "TOPIC",
    "BUCKET",
    "STREAM",
    "_BUS",
    "stack_name",
)
# Whole words: "draws from the queue" doesn't talk about AWS.
_AWS_WORDS = re.compile(r"(?i)(?<![a-z])(?:aws|sqs|sns)(?![a-z])|amazon|dynamodb|boto3|serverless")
_SSM_WORDS = re.compile(r"(?i)parameter|ssm")
# metadata.yaml-style maps of SSM paths: `OrdersTableName: /shop/{Environment}/orders/table`.
_SSM_PATH = re.compile(
    r"""^\s*["']?([A-Za-z][\w-]{0,80})["']?\s*:\s*["']?(/(?:[\w.{}$:-]+/){2,}[\w.{}$:-]+)["']?\s*$"""
)
_NOT_SSM_KEYS = re.compile(
    r"(?i)path|dir|mount|file|volume|home|root|work|command|entry|route|prefix|target|source"
    r"|location|log|url|endpoint|image|context|include"
)
_NOT_SSM_ROOTS = frozenset(
    {"var", "usr", "etc", "opt", "tmp", "home", "app", "srv", "mnt", "data", "dev", "proc"}
    | {"sys", "bin", "lib", "root", "run", "api", "v1", "v2", "src", "static", "health"}
)


class AwsDetector:
    id = "aws"

    def run(self, ctx: DetectorContext) -> DetectorResult:
        exposes: list[Fact] = []
        consumes: list[Fact] = []
        for path in ctx.files(_wanted):
            text = ctx.read(path)
            if not text or len(text) > _TEXT_MAX or not _relevant(path.name, text):
                continue
            lines = text.splitlines()
            for found in scan_file(path.name, text, lines)[:MAX_FACTS_PER_FILE]:
                line = lines[found.line_no - 1] if 0 < found.line_no <= len(lines) else ""
                kind = FactKind.TOPIC if found.topic else FactKind.CLOUD_RESOURCE
                evidence = (ctx.evidence(path, found.line_no, line[:_LINE_MAX]),)
                fact = Fact(kind=kind, value=found.value, evidence=evidence)
                (exposes if found.side == "exposes" else consumes).append(fact)
        return DetectorResult(exposes=merge_facts(exposes), consumes=merge_facts(consumes))


def scan_file(name: str, text: str, lines: list[str]) -> list[Found]:
    lowered = name.lower()
    suffix = PurePosixPath(lowered).suffix
    found: list[Found] = []
    expand: Expand = lambda line: line  # noqa: E731
    if suffix in _DATA:
        doc = aws_templates.load(lowered, text) if _maybe_template(text) else None
        if isinstance(doc, dict) and aws_templates.is_template(doc):
            expand = aws_templates.expander(doc)
            found += aws_templates.scan(doc, lines, expand)
    elif lowered == "samconfig.toml":
        found += aws_templates.samconfig(lines)
    elif suffix == ".tf":
        found += aws_terraform.scan(lines)
        found += aws_code.scan(lines, text, code=False)
    else:
        found += aws_code.scan(lines, text, code=True)
    yaml = suffix in (".yml", ".yaml")
    # `TABLE_NAME = "orders"` in a Postgres app names no DynamoDB table: env-style names only
    # count in files that talk about AWS at all.
    envs = _AWS_WORDS.search(text) is not None
    # A YAML map of paths is SSM's only in a file that talks about parameters.
    ssm_paths = yaml and _SSM_WORDS.search(text) is not None
    found += _lines(lines, expand, bare=yaml, envs=envs, ssm_paths=ssm_paths)
    return found


def _lines(
    lines: list[str], expand: Expand, *, bare: bool, envs: bool, ssm_paths: bool
) -> list[Found]:
    found = []
    for number, raw in enumerate(lines, start=1):
        stripped = raw.lstrip()
        if not stripped or stripped.startswith(_COMMENT):
            continue
        line = expand(raw[:_LINE_MAX])[:_LINE_MAX]
        found += [Found("consumes", v, number) for v in line_references(line)]
        if envs:
            found += [Found("consumes", v, number) for v in env_references(line, bare=bare)]
        if ssm_paths and ": /" in line.replace("'", "").replace('"', ""):
            found += [Found("consumes", v, number) for v in _ssm_path(line)]
    return found


def _ssm_path(line: str) -> list[str]:
    match = _SSM_PATH.match(line)
    if not match or _NOT_SSM_KEYS.search(match.group(1)):
        return []
    root = match.group(2).strip("/").split("/", 1)[0].lower()
    if root in _NOT_SSM_ROOTS:
        return []
    found = value("ssm", match.group(2))
    return [found] if found else []


def _maybe_template(text: str) -> bool:
    return "AWS::" in text or ("service" in text and ("provider" in text or "functions" in text))


def _wanted(name: str) -> bool:
    lowered = name.lower()
    if lowered.endswith(_SKIPPED):
        return False
    suffix = PurePosixPath(lowered).suffix
    return suffix in _CODE or suffix in _DATA or suffix == ".tf" or lowered == "samconfig.toml"


def _relevant(name: str, text: str) -> bool:
    if any(key in text for key in _GATE):
        return True
    return name.lower().endswith((".yml", ".yaml")) and ": /" in text
