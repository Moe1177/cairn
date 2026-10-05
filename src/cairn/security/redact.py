"""Remove secrets from text before cairn stores or prints it."""

import math
import re
from collections import Counter

REDACTED = "[REDACTED]"

_SECRET_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bsk_(?:live|test)_[A-Za-z0-9]{8,}",
        r"\bsk-[A-Za-z0-9_\-]{16,}",
        r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}",
        r"\bgithub_pat_[A-Za-z0-9_]{20,}",
        r"\bAKIA[0-9A-Z]{16}\b",
        r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
        r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    )
)
_URL_CREDENTIALS = re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+@")
_LONG_TOKEN = re.compile(r"[A-Za-z0-9_\-]{32,}")


def redact(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    text = _URL_CREDENTIALS.sub(f"{REDACTED}@", text)
    return _LONG_TOKEN.sub(_redact_if_random, text)


def make_snippet(line: str, max_len: int = 160) -> str:
    text = redact(line.strip())
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _redact_if_random(match: re.Match[str]) -> str:
    token = match.group(0)
    digits = sum(ch.isdigit() for ch in token)
    letters = sum(ch.isalpha() for ch in token)
    return REDACTED if digits >= 4 and letters >= 4 and _entropy(token) >= 3.5 else token


def _entropy(token: str) -> float:
    counts = Counter(token)
    size = len(token)
    return -sum((n / size) * math.log2(n / size) for n in counts.values())
