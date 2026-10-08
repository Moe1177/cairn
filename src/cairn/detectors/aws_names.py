"""AWS resource names (spec §25): one comparable value per resource, `<kind>:<name>`.

Names in IaC are templates (`orders-${sls:stage}`, `${var.env}-orders`, `/shop/{Env}/orders`) and
references are often literal (`arn:aws:sqs:us-east-1:123456789012:orders-prod`). Both sides are
reduced the same way: placeholders, regions, account ids and stage words drop out, so
`orders-${sls:stage}` and `orders-prod` both read `orders`. Anything that still looks like an
expression (a wildcard, a space, an unclosed brace) is no name at all.
"""

import re
from collections.abc import Callable, Iterator
from typing import NamedTuple

KIND_LABELS = {
    "sqs": "SQS queue",
    "sns": "SNS topic",
    "dynamodb": "DynamoDB table",
    "s3": "S3 bucket",
    "events": "EventBridge bus",
    "kinesis": "Kinesis stream",
    "ssm": "SSM parameter",
    "export": "CloudFormation export",
    "stack": "stack",
}
# Topic facts for EventBridge sources share the pub/sub matcher with Kafka and friends.
EVENT_SOURCE = "eventbridge:"

_TEXT_MAX = 512
_PLACEHOLDER = re.compile(
    r"\$\{[^{}]{0,200}\}"  # ${sls:stage}, ${var.env}, !Sub ${Environment}
    r"|\{\{[^{}]{0,200}\}\}"  # {{resolve:...}}, Jinja
    r"|#\{[^{}]{0,200}\}"  # serverless-pseudo-parameters
    r"|\{[A-Za-z_][\w.:-]{0,80}\}"  # /shop/{Environment}/x (filled in by a deploy script)
)
_REGION = re.compile(
    r"(?<![a-z0-9])(?:us|eu|ap|sa|ca|me|af|il|mx)-(?:gov-)?"
    r"(?:north|south|east|west|central)(?:east|west)?-\d(?![a-z0-9])"
)
_ACCOUNT = re.compile(r"(?<![0-9])\d{12}(?![0-9])")
_STAGE = re.compile(
    r"(?<![a-z0-9])(?:dev|develop|development|prod|production|staging|stage|stg|test|qa|uat"
    r"|sandbox|local|preprod)(?![a-z0-9])"
)
_RUNS = re.compile(r"([-_.])[-_.]+")
_AROUND_SLASH = re.compile(r"[-_.]*/+[-_.]*")
_NAME = re.compile(r"[a-z0-9][a-z0-9._:/+=@-]{1,254}")
_SEPARATORS = frozenset("-_.:/")
# Names that say nothing about which resource is meant.
_GENERIC = frozenset(
    {
        "queue",
        "topic",
        "table",
        "bucket",
        "stream",
        "events",
        "event",
        "default",
        "main",
        "data",
        "logs",
        "assets",
        "uploads",
        "artifacts",
        "deployments",
        "deployment",
        "state",
        "tfstate",
        "lock",
        "locks",
        "true",
        "false",
        "none",
        "null",
        "arn",
        "http",
        "https",
        "name",
    }
)

Expand = Callable[[str], str]


class Found(NamedTuple):
    """One thing a file says about a resource, before it becomes a Fact with evidence."""

    side: str  # "exposes" (creates it) or "consumes" (uses it)
    value: str
    line_no: int
    topic: bool = False  # an EventBridge source (a pub/sub topic), not a resource


def strip_placeholders(text: str) -> str:
    """Drop every placeholder; nested ones (`${self:x.${sls:stage}}`) unwrap from the inside."""
    for _ in range(4):
        stripped = _PLACEHOLDER.sub("", text)
        if stripped == text:
            break
        text = stripped
    return text


def clean(raw: str, kind: str) -> str | None:
    """The comparable name for `raw`, or None when it isn't a specific, literal name."""
    if not raw or len(raw) > _TEXT_MAX:
        return None
    text = strip_placeholders(raw.strip())
    if any(ch in text for ch in "${}*?\"' \t()[]<>,;|\\"):
        return None  # still an expression, a wildcard, or a list
    text = _STAGE.sub("", _ACCOUNT.sub("", _REGION.sub("", text.lower())))
    if kind == "ssm":
        text = "/" + _RUNS.sub(r"\1", _AROUND_SLASH.sub("/", text)).strip("-_./")
        core = text[1:]
    else:
        text = core = _RUNS.sub(r"\1", text).strip("-_.:/")
    if not _NAME.fullmatch(core) or not any(ch.isalpha() for ch in core):
        return None
    if len(core) < 3 or core in _GENERIC:
        return None
    return text


def value(kind: str, raw: str) -> str | None:
    name = clean(raw, kind)
    return f"{kind}:{name}" if name else None


def is_distinctive(name: str) -> bool:
    """A name with a separator in it (`orders-service-tablename`) rather than one word, which a
    stack-relative export (`${AWS::StackName}-TableName`) reduces to."""
    return any(ch in _SEPARATORS for ch in name.split(":", 1)[1].lstrip("/"))


# --- references that can appear on any line --------------------------------------------------

_PH = r"\$\{[^{}]{0,200}\}"
_ARN = re.compile(
    rf"arn:aws[\w-]{{0,20}}:(sqs|sns|dynamodb|s3|events|kinesis|ssm):((?:{_PH}|[^\s'\"`,;()\[\]{{}}<>\\])+)"
)
_QUEUE_URL = re.compile(
    rf"https://sqs\.(?:{_PH}|[\w.-])*amazonaws\.com/(?:{_PH}|[\w-])*/((?:{_PH}|[\w.-])+)"
)
_SSM_REF = re.compile(rf"\$\{{ssm(?:\([^(){{}}]*\))?:((?:{_PH}|[^{{}},~])+)")
_RESOLVE_SSM = re.compile(rf"\{{\{{resolve:ssm(?:-secure)?:((?:{_PH}|[^{{}}:])+)")
_CF_REF = re.compile(rf"\$\{{cf(?:\([^(){{}}]*\))?:((?:{_PH}|[^{{}}.])+)\.[\w-]+\}}")
_ARN_PREFIX = {"dynamodb": "table/", "kinesis": "stream/", "events": "event-bus/"}


def line_references(line: str) -> Iterator[str]:
    """Every resource a line points at by ARN, queue URL, or a serverless/CloudFormation lookup."""
    if "ssm" in line:
        for regex in (_SSM_REF, _RESOLVE_SSM):
            for match in regex.finditer(line):
                found = value("ssm", match.group(1))
                if found:
                    yield found
    if "${cf" in line:
        for match in _CF_REF.finditer(line):
            found = value("stack", match.group(1))
            if found:
                yield found
    if "arn:aws" in line:
        for match in _ARN.finditer(line):
            found = from_arn(match.group(1), match.group(2))
            if found:
                yield found
    if "amazonaws.com" in line:
        for match in _QUEUE_URL.finditer(line):
            found = value("sqs", match.group(1))
            if found:
                yield found


def from_arn(service: str, rest: str) -> str | None:
    """`sqs`, `region:account:orders` -> `sqs:orders`; None for ARNs naming no single resource."""
    parts = strip_placeholders(rest).split(":", 2)
    if len(parts) < 3 or not parts[2]:
        return None
    resource = parts[2]
    if service in ("sqs", "sns"):
        return value(service, resource.split(":", 1)[0])
    if service == "s3":
        return value("s3", resource.split("/", 1)[0])
    if service == "ssm":
        name = resource.removeprefix("parameter")
        return value("ssm", name) if name != resource else None
    prefix = _ARN_PREFIX[service]
    if not resource.startswith(prefix):
        return None  # a rule, an index, an archive: not the resource itself
    return value(service, resource[len(prefix) :].split("/", 1)[0])


# --- environment variables that name a resource ----------------------------------------------

_ENV_KINDS = {
    "TABLE": "dynamodb",
    "QUEUE": "sqs",
    "TOPIC": "sns",
    "BUCKET": "s3",
    "STREAM": "kinesis",
    "BUS": "events",
}
# The kind word is a whole `_`-separated word: UPSTREAM, STABLE and TIMETABLE are not names.
_ENV_KEY = (
    r"(?<![A-Za-z0-9_])[\"']?((?:[A-Z0-9]{1,30}_){0,6}(TABLE|QUEUE|TOPIC|BUCKET|STREAM|BUS)"
    r"(?:_NAME)?)[\"']?"
)
# Other brokers' and clouds' queues, topics and buckets.
_NOT_AWS_KEYS = re.compile(
    r"KAFKA|RABBIT|AMQP|NATS|REDIS|PUBSUB|MQTT|CELERY|SIDEKIQ|BULL|GCS|GCP|GOOGLE|AZURE|MINIO|R2_"
)
_ENV_QUOTED = re.compile(
    rf"{_ENV_KEY}\s*[:=]\s*[\"']((?:{_PH}|[A-Za-z0-9._/-])+)[\"'](?:\s*,)?\s*$"
)
_ENV_BARE = re.compile(rf"{_ENV_KEY}\s*[:=]\s*((?:{_PH}|[A-Za-z0-9._/-])+)\s*$")


def env_references(line: str, *, bare: bool) -> Iterator[str]:
    """`ORDERS_TABLE: orders-prod` names a DynamoDB table. `bare` allows unquoted (YAML) values."""
    if not any(word in line for word in _ENV_KINDS):
        return
    stripped = line.strip().removeprefix("- ")
    match = _ENV_QUOTED.search(stripped) or (_ENV_BARE.search(stripped) if bare else None)
    if match and not _NOT_AWS_KEYS.search(match.group(1)):
        found = value(_ENV_KINDS[match.group(2)], match.group(3))
        if found:
            yield found


def event_source(raw: str) -> str | None:
    """An EventBridge source a service publishes or a rule matches; AWS's own (`aws.ec2`) are
    not your services."""
    name = raw.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._/-]{2,99}", name) or name.startswith("aws."):
        return None
    return f"{EVENT_SOURCE}{name}"
