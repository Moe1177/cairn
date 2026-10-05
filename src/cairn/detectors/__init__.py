"""Detector registry. Identity detectors run first; relation detectors get the alias table."""

from cairn.detectors.base import Detector
from cairn.detectors.database import DatabaseDetector
from cairn.detectors.docs import DocsDetector
from cairn.detectors.identity import IdentityDetector
from cairn.detectors.packages import PackagesDetector
from cairn.detectors.pathrefs import PathRefsDetector
from cairn.detectors.profile import ProfileDetector

IDENTITY_DETECTORS: tuple[Detector, ...] = (IdentityDetector(), ProfileDetector())
RELATION_DETECTORS: tuple[Detector, ...] = (
    PackagesDetector(),
    DatabaseDetector(),
    PathRefsDetector(),
    DocsDetector(),
)
