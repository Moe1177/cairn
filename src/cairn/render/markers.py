"""Insert, replace, and remove a cairn-owned block inside a user's file."""

import re

from cairn.errors import CairnError

START = "<!-- cairn:start -->"
END = "<!-- cairn:end -->"
_BLOCK = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
_BLOCK_WITH_PADDING = re.compile(r"(?:\r?\n)?" + _BLOCK.pattern + r"(?:\r?\n)?", re.S)


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def upsert_block(original: str, body: str) -> str:
    _require_paired_markers(original)
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
    _require_paired_markers(original)
    return _BLOCK_WITH_PADDING.sub("", original)


def _require_paired_markers(text: str) -> None:
    """Refuse to edit when markers don't pair up; guessing could delete the user's text."""
    starts = [m.start() for m in re.finditer(re.escape(START), text)]
    ends = [m.start() for m in re.finditer(re.escape(END), text)]
    ordered = all(s < e for s, e in zip(starts, ends, strict=False)) and all(
        e < s for e, s in zip(ends, starts[1:], strict=False)
    )
    if len(starts) != len(ends) or not ordered:
        raise CairnError(
            f"found an incomplete cairn block ({START} / {END} lines don't pair up). "
            "Fix or delete those marker lines by hand, then re-run."
        )
