"""How much a shared value says about two repos being related."""

from collections.abc import Iterable

from cairn.model.graph import Confidence

DEFAULT_TABLE_STOPLIST = frozenset(
    {
        "users", "user", "accounts", "account", "sessions", "session", "migrations",
        "schema_migrations", "_prisma_migrations", "settings", "logs", "events",
        "verification_tokens", "verification",
    }
)
SIGNAL_STRENGTH = 0.6
EXTRACTED_THRESHOLD = 0.8
INFERRED_THRESHOLD = 0.4


def specificity(df: int) -> float:
    """1.0 for a value shared by exactly two repos, shrinking as more repos share it."""
    return 0.0 if df < 2 else 1.0 / (df - 1)


def noisy_or(weights: Iterable[float]) -> float:
    remaining = 1.0
    for weight in weights:
        remaining *= 1.0 - SIGNAL_STRENGTH * weight
    return round(1.0 - remaining, 4)


def db_confidence(score: float) -> Confidence | None:
    if score >= EXTRACTED_THRESHOLD:
        return Confidence.EXTRACTED
    if score >= INFERRED_THRESHOLD:
        return Confidence.INFERRED
    return Confidence.AMBIGUOUS if score > 0 else None
