"""Terraform (spec §25): `resource` blocks create AWS resources, `data` blocks read ones that
exist already (usually because another repo creates them).

HCL is read line by line with a brace count: a block's top-level `name = "..."` is its name.
Only literal (possibly interpolated) strings count; `name = local.queue_name` names nothing we
can compare. The `terraform { backend "s3" { bucket = ... } }` block is neither, so the state
bucket every repo shares never becomes a link.
"""

import re

from cairn.detectors.aws_names import Found, value

_BLOCK = re.compile(r'^\s*(resource|data|module)\s+"([\w-]{1,80})"(?:\s+"[^"]{0,200}")?\s*\{')
_ATTR = re.compile(r'^\s*([a-z_]{1,40})\s*=\s*"([^"]{0,500})"\s*(?:#.*|//.*)?$')
_INLINE_ATTR = re.compile(r'([a-z_]{1,40})\s*=\s*"([^"]{0,500})"')
_MODULE_SOURCE = re.compile(r"terraform-aws-modules/([\w-]{1,40})/aws")
_COMMENT = ("#", "//", "/*", "*")
_LINE_MAX = 2000
_RESOURCES = {
    "aws_sqs_queue": ("sqs", "name"),
    "aws_sns_topic": ("sns", "name"),
    "aws_dynamodb_table": ("dynamodb", "name"),
    "aws_s3_bucket": ("s3", "bucket"),
    "aws_kinesis_stream": ("kinesis", "name"),
    "aws_cloudwatch_event_bus": ("events", "name"),
    "aws_ssm_parameter": ("ssm", "name"),
}
_DATA = {
    **_RESOURCES,
    "aws_cloudformation_export": ("export", "name"),
    "aws_cloudformation_stack": ("stack", "name"),
}
# The community modules (registry.terraform.io/namespaces/terraform-aws-modules).
_MODULES = {
    "sqs": ("sqs", "name"),
    "sns": ("sns", "name"),
    "dynamodb-table": ("dynamodb", "name"),
    "s3-bucket": ("s3", "bucket"),
    "eventbridge": ("events", "bus_name"),
}


def scan(lines: list[str]) -> list[Found]:
    found: list[Found] = []
    depth = 0
    block: tuple[str, str] | None = None
    attrs: dict[str, tuple[str, int]] = {}
    for number, full in enumerate(lines, start=1):
        line = full[:_LINE_MAX]
        stripped = line.strip()
        if not stripped or stripped.startswith(_COMMENT):
            continue
        if depth == 0:
            opened = _BLOCK.match(line)
            block = (opened.group(1), opened.group(2)) if opened else None
            # A one-line block: `data "aws_sqs_queue" "q" { name = "orders" }`.
            rest = line[opened.end() :] if opened else ""
            attrs = {m.group(1): (m.group(2), number) for m in _INLINE_ATTR.finditer(rest)}
        elif depth == 1 and block is not None:
            attr = _ATTR.match(line)
            if attr:
                attrs.setdefault(attr.group(1), (attr.group(2), number))
        depth = max(0, depth + line.count("{") - line.count("}"))
        if depth == 0 and block is not None:
            hit = _finish(block, attrs)
            if hit:
                found.append(hit)
            block = None
    return found


def _finish(block: tuple[str, str], attrs: dict[str, tuple[str, int]]) -> Found | None:
    keyword, type_ = block
    if keyword == "module":
        source = _MODULE_SOURCE.search(attrs.get("source", ("", 0))[0])
        spec = _MODULES.get(source.group(1)) if source else None
        side = "exposes"
    else:
        spec = (_RESOURCES if keyword == "resource" else _DATA).get(type_)
        side = "exposes" if keyword == "resource" else "consumes"
    if spec is None or spec[1] not in attrs:
        return None
    raw, number = attrs[spec[1]]
    resource = value(spec[0], raw)
    return Found(side, resource, number) if resource else None
