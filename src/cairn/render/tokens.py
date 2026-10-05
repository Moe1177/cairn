"""Fast local token estimate (about 4 characters per token for English and code)."""

import math


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / 4)
