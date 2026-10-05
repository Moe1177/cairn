"""Insert, replace, and remove a cairn-owned block inside a user's file."""

import re

from cairn.errors import CairnError

START = "<!-- cairn:start -->"
END = "<!-- cairn:end -->"
TOML_START = "# cairn:start"
TOML_END = "# cairn:end"


def _block(start: str, end: str) -> re.Pattern[str]:
    return re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)


def _padded(start: str, end: str) -> re.Pattern[str]:
    return re.compile(r"(?:\r?\n)?" + _block(start, end).pattern + r"(?:\r?\n)?", re.S)


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def upsert_block(original: str, body: str, *, start: str = START, end: str = END) -> str:
    _require_paired_markers(original, start, end)
    newline = _newline(original)
    block = newline.join([start, *body.strip("\r\n").splitlines(), end])
    pattern = _block(start, end)
    if pattern.search(original):
        first, *rest = pattern.finditer(original)
        result = original
        for match in reversed(rest):
            result = result[: match.start()] + result[match.end() :]
        return result[: first.start()] + block + result[first.end() :]
    if not original:
        return block + newline
    separator = "" if original.endswith(newline) else newline
    return f"{original}{separator}{newline}{block}{newline}"


def remove_block(original: str, *, start: str = START, end: str = END) -> str:
    _require_paired_markers(original, start, end)
    return _padded(start, end).sub("", original)


def _require_paired_markers(text: str, start: str = START, end: str = END) -> None:
    """Refuse to edit when markers don't pair up; guessing could delete the user's text."""
    starts = [m.start() for m in re.finditer(re.escape(start), text)]
    ends = [m.start() for m in re.finditer(re.escape(end), text)]
    ordered = all(s < e for s, e in zip(starts, ends, strict=False)) and all(
        e < s for e, s in zip(ends, starts[1:], strict=False)
    )
    if len(starts) != len(ends) or not ordered:
        raise CairnError(
            f"found an incomplete cairn block ({start} / {end} lines don't pair up). "
            "Fix or delete those marker lines by hand, then re-run."
        )
