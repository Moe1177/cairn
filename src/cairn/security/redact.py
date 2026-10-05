"""Remove secrets from text before cairn stores or prints it (spec §20.1).

Over-redaction is fine: snippets are hints for agents, and a lost value costs nothing. A leaked
secret can't be taken back.
"""

import math
import re
from collections import Counter

REDACTED = "[REDACTED]"
# Redaction runs on at most this much text, which keeps every pattern's cost bounded.
MAX_REDACT_INPUT = 2048

_SECRET_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bsk_(?:live|test)_[A-Za-z0-9]{8,}",
        r"\bsk-[A-Za-z0-9_\-]{16,}",
        r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}",
        r"\bgithub_pat_[A-Za-z0-9_]{20,}",
        r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",
        r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
        r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        r"\b(?:sb_secret|sb_publishable|rk_live|rk_test|whsec|glpat|npm)[_-][A-Za-z0-9_\-]{10,}",
        r"(?i)\bBearer\s+[^\s'\"]+",
        r"(?i)\b(?:Basic|Token|Digest)\s+[A-Za-z0-9+/=._~\-]{8,}",
    )
)
# Any URL userinfo: "user@", "user:pass@", ":pass@", a password containing "/" or "@".
_URL_CREDENTIALS = re.compile(r"(?<=://)[^\s@/:]*(?::[^\s]*)?@")
# `password = x`, `"api_key": "x"`, `Password=x;`, `aws_secret_access_key=x`, `?token=x`.
# A bounded key, then the separator, then the value; whether the key names a secret is checked
# in Python. (A keyword alternation inside an unbounded identifier went cubic on "authauth...".)
_KEY_VALUE = re.compile(r"([A-Za-z0-9_.\-]{1,64})(['\"]?\s*[:=]\s*['\"]?)([^'\"\s;,&]+)")
_SECRET_KEY = re.compile(
    r"(?i)passw(?:or)?d|pwd|secret|token|api[_\-]?key|access[_\-]?key|private[_\-]?key"
    r"|auth(?!or)|credential"
)
# Literal rows in SQL seeds or fixtures: everything after VALUES may be data.
_SQL_VALUES = re.compile(r"(?i)(\bVALUES\s*\().*")
_LONG_TOKEN = re.compile(r"[A-Za-z0-9+/=_\-]{32,}")


def redact(text: str) -> str:
    text = text[:MAX_REDACT_INPUT]
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    text = _URL_CREDENTIALS.sub(f"{REDACTED}@", text)
    text = _SQL_VALUES.sub(rf"\1{REDACTED})", text)
    text = _KEY_VALUE.sub(_redact_if_secret_key, text)
    return _LONG_TOKEN.sub(_redact_if_random, text)


def make_snippet(line: str, max_len: int = 160) -> str:
    text = redact(line.strip()[: max_len * 2])
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _redact_if_secret_key(match: re.Match[str]) -> str:
    key, separator, value = match.groups()
    return f"{key}{separator}{REDACTED}" if _SECRET_KEY.search(key) else match.group(0)


def _redact_if_random(match: re.Match[str]) -> str:
    token = match.group(0)
    if REDACTED in token:
        return token
    digits = sum(ch.isdigit() for ch in token)
    letters = sum(ch.isalpha() for ch in token)
    return REDACTED if digits >= 4 and letters >= 4 and _entropy(token) >= 3.5 else token


def _entropy(token: str) -> float:
    counts = Counter(token)
    size = len(token)
    return -sum((n / size) * math.log2(n / size) for n in counts.values())
