"""Detector registry. Identity detectors run first; relation detectors get the alias table."""

from cairn.detectors.base import Detector
from cairn.detectors.database import DatabaseDetector
from cairn.detectors.docs import DocsDetector
from cairn.detectors.http import HttpDetector
from cairn.detectors.identity import IdentityDetector
from cairn.detectors.infra import InfraDetector
from cairn.detectors.messaging import MessagingDetector
from cairn.detectors.packages import PackagesDetector
from cairn.detectors.pathrefs import PathRefsDetector
from cairn.detectors.profile import ProfileDetector

IDENTITY_DETECTORS: tuple[Detector, ...] = (IdentityDetector(), ProfileDetector())
RELATION_DETECTORS: tuple[Detector, ...] = (
    PackagesDetector(),
    DatabaseDetector(),
    PathRefsDetector(),
    HttpDetector(),
    MessagingDetector(),
    InfraDetector(),
    DocsDetector(),
)

# Detectors whose output depends on other repos (the alias table, which sibling paths
# exist, where this repo sits) and so always re-run instead of being cached per repo.
LIVE_DETECTOR_IDS = frozenset({"docs", "pathrefs", "infra"})
