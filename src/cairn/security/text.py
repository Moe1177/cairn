"""Make text taken from scanned repos safe to render (spec §20.1).

Anything a repo controls (folder and package names, README text, layout entries) is data. It is
flattened to one line, stripped of control characters, comment markers, and backticks, and capped,
so it can't break out of a Markdown line, a code span, or cairn's marked blocks.
"""

import re

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_COMMENT = re.compile(r"<!--|-->")
_ALIAS = re.compile(r"[a-z0-9@][a-z0-9@/._-]{0,63}")


def clean_inline(text: str, limit: int) -> str:
    """One safe line of at most `limit` characters."""
    flat = " ".join(text.split())
    flat = _CONTROL.sub("", _COMMENT.sub("", flat)).replace("`", "'")
    flat = " ".join(flat.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def valid_alias(name: str) -> bool:
    """Package-style names only: lowercase, no spaces, at most 64 characters."""
    return _ALIAS.fullmatch(name) is not None
