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
