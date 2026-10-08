"""CloudFormation, SAM and Serverless Framework templates (spec §25).

A template *creates* the resources it declares with a name (`QueueName: orders-${sls:stage}`)
and the CloudFormation exports in its Outputs; a serverless service is also a stack others can
read (`${cf:orders-service-dev.TopicArn}`). It *uses* what it imports (`Fn::ImportValue`), the
resources its policies and rule targets name (`DynamoDBCrudPolicy: {TableName: orders}`), the
SSM parameters its parameters default to, and the EventBridge sources its rules match.
ARNs anywhere in the file are read line by line elsewhere (aws_names.line_references).

Templates come from untrusted repos: anchors can make a small file a huge (or cyclic) tree, so
every walk visits each node once and every join, expansion and result list is bounded.
"""

import json
import re
from collections.abc import Callable, Iterable, Iterator

from cairn.detectors.aws_names import Expand, Found, event_source, value
from cairn.security.safe_yaml import load_template_yaml, too_deep

_MAX_NODES = 50_000  # distinct nodes walked
_MAX_FOUND = 2000
_MAX_SOURCES = 100
_TEXT_MAX = 512  # a name longer than this is no name (aws_names.clean agrees)
_EXPAND_MAX = 4096  # what `${self:...}` filling may add to one value or line
_JOIN_DEPTH = 2
_JOIN_PARTS = 20
_LINE_INDEX_MAX = 2000
_OWNED = {
    "AWS::SQS::Queue": ("sqs", "QueueName"),
    "AWS::SNS::Topic": ("sns", "TopicName"),
    "AWS::DynamoDB::Table": ("dynamodb", "TableName"),
    "AWS::DynamoDB::GlobalTable": ("dynamodb", "TableName"),
    "AWS::Serverless::SimpleTable": ("dynamodb", "TableName"),
    "AWS::S3::Bucket": ("s3", "BucketName"),
    "AWS::Events::EventBus": ("events", "Name"),
    "AWS::Kinesis::Stream": ("kinesis", "Name"),
    "AWS::SSM::Parameter": ("ssm", "Name"),
    "AWS::Lambda::Function": ("lambda", "FunctionName"),
    "AWS::Serverless::Function": ("lambda", "FunctionName"),
}
# Keys naming a resource used from elsewhere: SAM policy templates, rule targets, data sources,
# a serverless eventBridge event's bus.
_USED = {
    "TableName": "dynamodb",
    "QueueName": "sqs",
    "TopicName": "sns",
    "BucketName": "s3",
    "EventBusName": "events",
    "StreamName": "kinesis",
    "ParameterName": "ssm",
    "FunctionName": "lambda",
    "eventBus": "events",
}
_PATTERN_KEYS = frozenset({"pattern", "Pattern", "EventPattern", "eventPattern"})
# Tables that aren't DynamoDB's: their `TableName` names nothing a DynamoDB table could match.
_OTHER_TABLES = (
    "AWS::Timestream::",
    "AWS::Glue::",
    "AWS::Cassandra::",
    "AWS::LakeFormation::",
    "AWS::KinesisFirehose::",
    "AWS::Athena::",
    "AWS::Redshift",
)
_SELF = re.compile(r"\$\{self:([\w.-]{1,120})\}")
_STACK_NAME = re.compile(r"""^\s*stack_name\s*=\s*["']([^"']+)["']""")
_LINE_KEY = re.compile(r"""^["']?([A-Za-z_][\w.:-]{0,120}?)["']?\s*:(?:\s+(.*))?$""")
_TAG = re.compile(r"^!\w+(?:::\w+)?\s+")


def load(name: str, text: str) -> object:
    if name.endswith(".json"):
        if too_deep(text):
            return None
        try:
            return json.loads(text)
        except (ValueError, RecursionError):
            return None
    return load_template_yaml(text)


def is_serverless(doc: object) -> bool:
    return isinstance(doc, dict) and "service" in doc and ("provider" in doc or "functions" in doc)


def is_template(doc: object) -> bool:
    return is_serverless(doc) or (isinstance(doc, dict) and isinstance(doc.get("Resources"), dict))


def expander(doc: object) -> Expand:
    """Fill in a serverless file's `${self:custom.tableName}` from the file itself, adding at
    most _EXPAND_MAX characters per round so references can't multiply a line's size."""

    def lookup(path: str) -> str | None:
        node = doc
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        if path == "service" and isinstance(node, dict):
            node = node.get("name")
        if isinstance(node, bool) or not isinstance(node, str | int):
            return None
        return str(node)

    def expand(text: str) -> str:
        for _ in range(3):
            filled = _fill_once(text, lookup)
            if filled == text:
                break
            text = filled
        return text

    return expand if is_serverless(doc) else (lambda text: text)


def _fill_once(text: str, lookup: Callable[[str], str | None]) -> str:
    budget = _EXPAND_MAX

    def fill(match: re.Match[str]) -> str:
        nonlocal budget
        found = lookup(match.group(1))
        if found is None or len(found) > budget:
            return match.group(0)  # unknown or over budget: stays a placeholder
        budget -= len(found)
        return found

    return _SELF.sub(fill, text)


def scan(doc: dict, raw_lines: list[str], expand: Expand) -> list[Found]:
    lines = Lines(raw_lines)
    serverless = is_serverless(doc)
    section = doc.get("resources") if serverless else doc
    section = section if isinstance(section, dict) else {}
    resources = section.get("Resources")
    resources = resources if isinstance(resources, dict) else {}
    found, owned_keys = _resources(resources, lines, expand)
    found += _outputs(section.get("Outputs"), lines, expand)
    found += _ssm_parameters(doc.get("Parameters"), lines)
    if serverless:
        found += _service(doc, lines, expand)
    found += _walk(doc, lines, expand, owned_keys)
    return found[:_MAX_FOUND]


def samconfig(lines: list[str]) -> list[Found]:
    """SAM's `stack_name = "orders"`: the stack a `${cf:orders.Output}` lookup reads."""
    found = []
    for number, line in enumerate(lines, start=1):
        match = _STACK_NAME.match(line)
        resource = value("stack", match.group(1)) if match else None
        if resource:
            found.append(Found("exposes", resource, number))
    return found


def string(node: object, expand: Expand, depth: int = 0) -> str | None:
    """A template value as a name template: `!Sub`, `!Join` and `!Ref` become `${...}` text;
    anything computed (`!GetAtt`, `!Select`), too deep or too long is no name."""
    if isinstance(node, str):
        text = expand(node)
        return text if len(text) <= _TEXT_MAX else None
    if isinstance(node, int) and not isinstance(node, bool):
        return str(node)
    if not isinstance(node, dict) or len(node) != 1:
        return None
    key, inner = next(iter(node.items()))
    if key == "Fn::Sub":
        text = inner[0] if isinstance(inner, list) and inner else inner
        return string(text, expand, depth) if isinstance(text, str) else None
    if key == "Ref":
        return f"${{{inner}}}" if isinstance(inner, str) else None
    if key == "Fn::Join" and depth < _JOIN_DEPTH and isinstance(inner, list) and len(inner) == 2:
        separator, parts = inner
        if isinstance(separator, str) and isinstance(parts, list):
            return _join(separator, parts[:_JOIN_PARTS], expand, depth)
    return None


def _join(separator: str, parts: list, expand: Expand, depth: int) -> str | None:
    texts: list[str] = []
    size = 0
    for part in parts:
        text = string(part, expand, depth + 1)
        if text is None:
            return None
        size += len(text) + len(separator)
        if size > _TEXT_MAX:
            return None
        texts.append(text)
    return separator.join(texts)


def _needle(node: object) -> str | None:
    if isinstance(node, str):
        return node
    if isinstance(node, dict) and len(node) == 1:
        inner = next(iter(node.values()))
        if isinstance(inner, list) and inner:
            inner = inner[0]
        return inner if isinstance(inner, str) else None
    return None


def _resources(
    resources: dict, lines: "Lines", expand: Expand
) -> tuple[list[Found], set[tuple[int, str]]]:
    """What the template creates, and the (node, key) pairs that name it (not a use)."""
    found: list[Found] = []
    owned_keys: set[tuple[int, str]] = set()
    for logical, spec in list(resources.items())[:_MAX_NODES]:
        if not isinstance(spec, dict) or not isinstance(spec.get("Type"), str):
            continue
        if spec["Type"].startswith(_OTHER_TABLES):
            owned_keys |= {(id(node), "TableName") for node in _nodes(spec)}
        owned = _OWNED.get(spec["Type"])
        props = spec.get("Properties")
        if owned is None or not isinstance(props, dict):
            continue
        kind, key = owned
        owned_keys.add((id(props), key))
        raw = props.get(key)
        name = string(raw, expand)
        resource = value(kind, name) if name else None
        if resource:
            line = lines.find(_needle(raw), key) or lines.find(str(logical)) or 1
            found.append(Found("exposes", resource, line))
    return found, owned_keys


def _outputs(outputs: object, lines: "Lines", expand: Expand) -> list[Found]:
    found = []
    for output in list(outputs.values())[:_MAX_NODES] if isinstance(outputs, dict) else ():
        export = output.get("Export") if isinstance(output, dict) else None
        raw = export.get("Name") if isinstance(export, dict) else None
        name = string(raw, expand)
        resource = value("export", name) if name else None
        if resource:
            line = lines.find(_needle(raw), "Name") or lines.find("Export") or 1
            found.append(Found("exposes", resource, line))
    return found


def _ssm_parameters(parameters: object, lines: "Lines") -> list[Found]:
    """`Type: AWS::SSM::Parameter::Value<String>` with a Default path reads that parameter."""
    found = []
    for spec in list(parameters.values())[:_MAX_NODES] if isinstance(parameters, dict) else ():
        if not isinstance(spec, dict):
            continue
        kind, default = spec.get("Type"), spec.get("Default")
        if not isinstance(default, str) or not isinstance(kind, str):
            continue
        if kind.startswith("AWS::SSM::Parameter::Value"):
            resource = value("ssm", default)
            if resource:
                found.append(Found("consumes", resource, lines.find(default, "Default") or 1))
    return found


def _service(doc: dict, lines: "Lines", expand: Expand) -> list[Found]:
    """The service is a stack and each function a Lambda (`<service>-<stage>-<key>` unless
    it sets `name:`); an `sns: name` event (not an ARN) makes serverless create the topic."""
    found = []
    raw = doc.get("service")
    raw = raw.get("name") if isinstance(raw, dict) else raw
    service = expand(raw) if isinstance(raw, str) else None
    if isinstance(raw, str) and service:
        stack = value("stack", service)
        if stack:
            found.append(Found("exposes", stack, lines.find(raw, "service") or 1))
    functions = doc.get("functions")
    for key, spec in list(functions.items())[:_MAX_NODES] if isinstance(functions, dict) else ():
        found += _function(str(key), spec, service, lines, expand)
        events = spec.get("events") if isinstance(spec, dict) else None
        for event in events[:_MAX_NODES] if isinstance(events, list) else ():
            sns = event.get("sns") if isinstance(event, dict) else None
            raw_topic = sns.get("topicName") if isinstance(sns, dict) and "arn" not in sns else sns
            if isinstance(raw_topic, str) and not raw_topic.startswith("arn:"):
                topic = value("sns", expand(raw_topic))
                if topic:
                    found.append(Found("exposes", topic, lines.find(raw_topic) or 1))
    return found


def _function(
    key: str, spec: object, service: str | None, lines: "Lines", expand: Expand
) -> list[Found]:
    custom = spec.get("name") if isinstance(spec, dict) else None
    if isinstance(custom, str):
        raw, line = expand(custom), lines.find(custom, "name")
    elif service:
        raw, line = f"{service}-${{sls:stage}}-{key}", lines.find(key)
    else:
        return []
    function = value("lambda", raw)
    return [Found("exposes", function, line or 1)] if function else []


def _walk(
    doc: object, lines: "Lines", expand: Expand, owned_keys: set[tuple[int, str]]
) -> list[Found]:
    found: list[Found] = []
    for node in _nodes(doc):
        if len(found) >= _MAX_FOUND:
            break
        for key, inner in node.items():
            if key == "Fn::ImportValue":
                found += _used("export", key, inner, lines, expand)
            elif key in _USED and (id(node), key) not in owned_keys:
                found += _used(_USED[key], key, inner, lines, expand)
            elif key in _PATTERN_KEYS and isinstance(inner, dict):
                found += _sources(inner.get("source"), lines)
    return found


def _used(kind: str, key: str, inner: object, lines: "Lines", expand: Expand) -> list[Found]:
    name = string(inner, expand)
    if not name or name.startswith("arn:"):
        return []  # an ARN is read from its line
    resource = value(kind, name)
    return [Found("consumes", resource, lines.find(_needle(inner), key) or 1)] if resource else []


def _sources(sources: object, lines: "Lines") -> list[Found]:
    listed = [sources] if isinstance(sources, str) else sources if isinstance(sources, list) else []
    found = []
    for raw in listed[:_MAX_SOURCES]:
        topic = event_source(raw) if isinstance(raw, str) else None
        if topic:
            found.append(Found("consumes", topic, lines.find(raw) or 1, topic=True))
    return found


def _nodes(doc: object) -> Iterator[dict]:
    """Every distinct dict in the tree, once each: an anchor used many times (or inside
    itself) is walked once, and the walk stops after _MAX_NODES distinct nodes."""
    stack, seen = [doc], {id(doc)}
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            yield node
            children: Iterable[object] = node.values()
        elif isinstance(node, list):
            children = node
        else:
            continue
        for child in children:
            if isinstance(child, dict | list) and id(child) not in seen:
                if len(seen) >= _MAX_NODES:
                    return
                seen.add(id(child))
                stack.append(child)


class Lines:
    """Where a template writes a value, indexed in one pass so each lookup is O(1).

    `key: value` lines are indexed by (key, value) and by value; list items (`- value`, and
    each item of `[a, b]`) by value. Tags (`!Sub`), quotes, trailing commas and comments are
    dropped, so `QueueName: !Sub "orders-${Stage}"` is found as ("QueueName", "orders-${Stage}").
    """

    def __init__(self, lines: list[str]) -> None:
        self._pairs: dict[tuple[str, str], int] = {}
        self._values: dict[str, int] = {}
        for number, line in enumerate(lines, start=1):
            text = line.strip()[:_LINE_INDEX_MAX]
            text = text[2:].lstrip() if text.startswith("- ") else text
            match = _LINE_KEY.match(text)
            if match:
                bare = _bare(match.group(2) or "")
                self._pairs.setdefault((match.group(1), bare), number)
                self._values.setdefault(match.group(1), number)
            else:
                bare = _bare(text)
            self._values.setdefault(bare, number)
            if bare.startswith("[") and bare.endswith("]"):
                for item in bare[1:-1].split(",")[:_MAX_SOURCES]:
                    self._values.setdefault(_bare(item), number)

    def find(self, needle: str | None, key: str | None = None) -> int | None:
        """The line writing `needle` (under `key` when given and found there)."""
        if not needle:
            return None
        paired = self._pairs.get((key, needle)) if key else None
        return paired or self._values.get(needle)


def _bare(text: str) -> str:
    text = text.split(" #", 1)[0].strip().rstrip(",").strip()
    return _TAG.sub("", text).strip().strip("\"'")
