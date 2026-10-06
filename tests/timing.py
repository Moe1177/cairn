"""Wall-clock limits for "this stays linear" tests that don't flake on slow or busy machines.

A regex that backtracks catastrophically on 1 MB takes minutes, so a limit only has to sit
an order of magnitude below that. Coverage tracing and parallel workers each slow a run
down, so the limit grows with them rather than failing a healthy build.
"""

import os
import sys


def time_limit(budget: float) -> float:
    scale = 1.0
    if sys.gettrace() is not None or "coverage" in sys.modules:
        scale *= 3
    if os.environ.get("PYTEST_XDIST_WORKER") or os.environ.get("CI"):
        scale *= 2
    return budget * scale
