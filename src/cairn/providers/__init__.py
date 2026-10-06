"""Deep-index providers (spec §6, §23). graphify is the first; the interface leaves room for more."""

from cairn.providers.graphify import GraphifyProvider


def default_provider() -> GraphifyProvider:
    """Looked up at call time, so tests can swap in a fake."""
    return GraphifyProvider()
