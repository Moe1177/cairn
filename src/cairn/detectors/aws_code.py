"""AWS resources named in code (spec §25): CDK stacks and AWS SDK calls.

CDK creates what its constructs name (`new sqs.Queue(this, 'Q', { queueName: 'orders' })`) and
uses what it looks up (`Table.fromTableName(this, 'T', 'orders')`, `Fn.importValue(...)`). SDK
calls use the resources they name literally (`TableName: 'orders'`, `get_parameter(Name=...)`),
and `PutEvents` entries publish their `Source`. Most code reads names from env vars instead;
those are found where the env var is set (aws_names.env_references).
"""

import re

from cairn.detectors.aws_names import Found, event_source, value

_Q = r"""["']([^"'\n]{1,256})["']"""
_GO = r"(?:aws\.String\()?"  # Go SDK: TableName: aws.String("orders")
_CDK_MARKERS = ("aws-cdk-lib", "@aws-cdk/", "aws_cdk", "software.amazon.awscdk")
_CDK_PROPS = {
    "queueName": "sqs",
    "queue_name": "sqs",
    "topicName": "sns",
    "topic_name": "sns",
    "tableName": "dynamodb",
    "table_name": "dynamodb",
    "bucketName": "s3",
    "bucket_name": "s3",
    "eventBusName": "events",
    "event_bus_name": "events",
    "streamName": "kinesis",
    "stream_name": "kinesis",
    "parameterName": "ssm",
    "parameter_name": "ssm",
    "exportName": "export",
    "export_name": "export",
}
_CDK_PROP = re.compile(rf"\b({'|'.join(_CDK_PROPS)})\s*[:=]\s*{_Q}")
# A prop inside `X.fromXAttributes(this, 'id', { tableName })` looks a resource up.
_LOOKUP = re.compile(r"\.from[A-Z]\w*\(|\.from_\w+\(")
_CREATE = re.compile(r"\bnew\s+[\w.]+\(|\b[A-Z]\w*\(\s*self\s*,")
_LOOKBACK = 6
_FROM_NAME = re.compile(
    r"\.(?:from(Table|Bucket|EventBus|Stream|Queue|Topic)Name"
    r"|from_(table|bucket|event_bus|stream|queue|topic)_name)"
    rf"\(\s*\w+\s*,\s*{_Q}\s*,\s*{_Q}"
)
_FROM_KINDS = {
    "table": "dynamodb",
    "bucket": "s3",
    "eventbus": "events",
    "event_bus": "events",
    "stream": "kinesis",
    "queue": "sqs",
    "topic": "sns",
}
_SSM_LOOKUP = (
    re.compile(
        r"(?:valueForStringParameter|valueForSecureStringParameter|valueFromLookup"
        r"|value_for_string_parameter|value_for_secure_string_parameter|value_from_lookup)"
        rf"\(\s*\w+\s*,\s*{_Q}"
    ),
    re.compile(
        r"(?:fromStringParameterName|fromSecureStringParameterName"
        r"|from_string_parameter_name|from_secure_string_parameter_name)"
        rf"\(\s*\w+\s*,\s*{_Q}\s*,\s*{_Q}"
    ),
)
_IMPORT = re.compile(rf"\bFn\.(?:importValue|import_value)\(\s*{_Q}")
_SDK = {
    "QueueName": "sqs",
    "TableName": "dynamodb",
    "TopicName": "sns",
    "Bucket": "s3",
    "StreamName": "kinesis",
    "EventBusName": "events",
}
_SDK_PARAM = re.compile(rf"""["']?\b({"|".join(_SDK)})["']?\s*[:=]\s*{_GO}{_Q}""")
_SDK_CREATE = re.compile(
    r"create_(?:queue|table|topic|bucket|stream)|Create(?:Queue|Table|Topic|Bucket|Stream)"
)
_BOTO_RESOURCE = re.compile(rf"\.(Table|Bucket)\(\s*{_Q}\s*\)")
_SSM_GET = re.compile(
    r"(get_parameters?|GetParameters?(?:Command)?|getParameters?|put_parameter|PutParameter(?:Command)?|putParameter)"
    rf"\((?:\s*\{{)?\s*[\"']?Name[\"']?\s*[:=]\s*{_GO}{_Q}"
)
# SDK patterns only count in files that use an AWS SDK: GORM's `db.Table("orders")`, Go's GCS
# `client.Bucket(...)` and a C# `const string TableName` are not DynamoDB or S3.
_SDK_MARKERS = (
    "boto3",
    "botocore",
    "@aws-sdk/",
    "aws-sdk",
    "github.com/aws/aws-sdk-go",
    "software.amazon.awssdk",
    "com.amazonaws",
    "Amazon.DynamoDBv2",
    "Amazon.SQS",
    "Amazon.SimpleNotificationService",
    "Amazon.S3",
)
# A construct prop inside an `environment: {...}` block is a Lambda env var, not a resource.
_ENVIRONMENT = re.compile(r"\benvironment\s*[:=]")
_LINE_MAX = 2000
# PutEvents entries: {"Source": "orders.service", "DetailType": ...}; Java's .source("...").
_PUT_SOURCE = (
    re.compile(rf"""["']?\bSource["']?\s*[:=]\s*{_GO}{_Q}"""),
    re.compile(rf"\.source\(\s*{_Q}\s*\)"),
)
_PUT_MARKERS = ("DetailType", "detailType", "detail_type")
# A rule's pattern in HCL, CDK or embedded JSON: source = ["orders.service"].
_PATTERN_SOURCE = re.compile(r"""["']?\bsource["']?\s*[:=]\s*\[([^\]\n]{1,500})\]""")
_PATTERN_MARKERS = ("event_pattern", "eventPattern", "EventPattern")
_QUOTED = re.compile(_Q)
_COMMENT = ("#", "//", "/*", "*")


def scan(lines: list[str], text: str, *, code: bool) -> list[Found]:
    """`code` is False for HCL and data files: only rule patterns are read from those."""
    found: list[Found] = []
    cdk = code and any(marker in text for marker in _CDK_MARKERS)
    sdk = code and any(marker in text for marker in _SDK_MARKERS)
    boto = sdk and "boto3" in text
    publishes = code and any(marker in text for marker in _PUT_MARKERS)
    patterns = any(marker in text for marker in _PATTERN_MARKERS)
    lines = [line[:_LINE_MAX] for line in lines]
    for number, line in enumerate(lines, start=1):
        if line.lstrip().startswith(_COMMENT):
            continue
        if patterns and "source" in line:
            found += [
                Found("consumes", topic, number, topic=True)
                for m in _PATTERN_SOURCE.finditer(line)
                for raw in _QUOTED.findall(m.group(1))
                if (topic := event_source(raw))
            ]
        if not code:
            continue
        if cdk:
            found += _cdk(lines, number, line)
        if sdk:
            found += _sdk(lines, number, line, boto=boto)
        if publishes and "ource" in line:
            found += [
                Found("exposes", topic, number, topic=True)
                for regex in _PUT_SOURCE
                for m in regex.finditer(line)
                if (topic := event_source(m.group(1)))
            ]
    return found


def _cdk(lines: list[str], number: int, line: str) -> list[Found]:
    found = []
    for match in _CDK_PROP.finditer(line):
        resource = value(_CDK_PROPS[match.group(1)], match.group(2))
        if resource:
            side = "consumes" if _looks_up_or_env(lines, number) else "exposes"
            found.append(Found(side, resource, number))
    for match in _FROM_NAME.finditer(line):
        kind = _FROM_KINDS[(match.group(1) or match.group(2)).lower()]
        resource = value(kind, match.group(4))
        if resource:
            found.append(Found("consumes", resource, number))
    for regex in _SSM_LOOKUP:
        for match in regex.finditer(line):
            resource = value("ssm", match.group(match.lastindex or 1))
            if resource:
                found.append(Found("consumes", resource, number))
    for match in _IMPORT.finditer(line):
        resource = value("export", match.group(1))
        if resource:
            found.append(Found("consumes", resource, number))
    return found


def _looks_up_or_env(lines: list[str], number: int) -> bool:
    """Whether the nearest construct call above (or on) this line is a `fromX` lookup, or the
    prop sits in an `environment:` block (a function's env var naming a resource it uses)."""
    for line in reversed(lines[max(0, number - _LOOKBACK) : number]):
        lookup, create = _LOOKUP.search(line), _CREATE.search(line)
        environment = _ENVIRONMENT.search(line)
        if environment and not (lookup or create):
            return True
        if lookup or create:
            if environment:
                return True
            return bool(lookup) and (not create or lookup.start() > create.start())
    return False


def _sdk(lines: list[str], number: int, line: str, *, boto: bool) -> list[Found]:
    found = []
    # `create_table(` often opens on the line above its `TableName=`.
    window = lines[max(0, number - 3) : number]
    creates = any(_SDK_CREATE.search(above) for above in window)
    side = "exposes" if creates else "consumes"
    for match in _SDK_PARAM.finditer(line):
        resource = value(_SDK[match.group(1)], match.group(2))
        if resource:
            found.append(Found(side, resource, number))
    for match in _BOTO_RESOURCE.finditer(line) if boto else ():
        kind = "dynamodb" if match.group(1) == "Table" else "s3"
        resource = value(kind, match.group(2))
        if resource:
            found.append(Found("consumes", resource, number))
    for match in _SSM_GET.finditer(line):
        resource = value("ssm", match.group(2))
        if resource:
            put = match.group(1).lower().startswith("put")
            found.append(Found("exposes" if put else "consumes", resource, number))
    return found
