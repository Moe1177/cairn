"""Insert, replace, and remove a cairn-owned block inside a user's file."""

import re

START = "<!-- cairn:start -->"
END = "<!-- cairn:end -->"
_BLOCK = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
_BLOCK_WITH_PADDING = re.compile(r"(?:\r?\n)?" + _BLOCK.pattern + r"(?:\r?\n)?", re.S)


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def upsert_block(original: str, body: str) -> str:
    newline = _newline(original)
    block = newline.join([START, *body.strip("\r\n").splitlines(), END])
    if _BLOCK.search(original):
        first, *rest = _BLOCK.finditer(original)
        result = original
        for match in reversed(rest):
            result = result[: match.start()] + result[match.end() :]
        return result[: first.start()] + block + result[first.end() :]
    if not original:
        return block + newline
    separator = "" if original.endswith(newline) else newline
    return f"{original}{separator}{newline}{block}{newline}"


def remove_block(original: str) -> str:
    return _BLOCK_WITH_PADDING.sub("", original)
