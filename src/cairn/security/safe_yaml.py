"""Parse YAML from repos without letting a hostile file crash the process (spec §20.1).

libyaml's C loader recurses natively while building nested nodes, so a few KB of `[[[[...`
can overflow the C stack and kill the interpreter; no `except` can catch that. A linear
pre-check refuses deep nesting before any parser sees the text.
"""

import yaml

MAX_DEPTH = 64
_Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def too_deep(text: str, limit: int = MAX_DEPTH) -> bool:
    """Flow nesting ([ {) deeper than `limit`, or block indentation beyond limit*4 columns."""
    depth = 0
    for ch in text:
        if ch in "[{":
            depth += 1
            if depth > limit:
                return True
        elif ch in "]}" and depth:
            depth -= 1
    for line in text.splitlines():
        stripped = line.lstrip(" -")
        if stripped and len(line) - len(stripped) > limit * 4:
            return True
    return False


def load_yaml(text: str) -> object:
    """The parsed document, or None for anything unparseable, too deep, or recursive."""
    if too_deep(text):
        return None
    try:
        return yaml.load(text, Loader=_Loader)  # noqa: S506 - a safe loader
    except (yaml.YAMLError, RecursionError, ValueError):
        return None


class _TemplateLoader(_Loader):  # type: ignore[misc,valid-type]
    """CloudFormation's short tags (`!Ref X`, `!Sub "..."`) read as their long form
    (`{"Ref": "X"}`, `{"Fn::Sub": "..."}`) instead of failing the whole document."""


def _short_tag(loader: yaml.SafeLoader, suffix: str, node: yaml.Node) -> object:
    value: object
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)  # type: ignore[arg-type]
    return {"Ref" if suffix == "Ref" else f"Fn::{suffix}": value}


_TemplateLoader.add_multi_constructor("!", _short_tag)


def load_template_yaml(text: str) -> object:
    """Like load_yaml, for CloudFormation/SAM/serverless templates and their short tags."""
    if too_deep(text):
        return None
    try:
        return yaml.load(text, Loader=_TemplateLoader)  # noqa: S506 - a safe loader + tags
    except (yaml.YAMLError, RecursionError, ValueError):
        return None
