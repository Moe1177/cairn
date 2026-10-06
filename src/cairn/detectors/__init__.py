"""Detector registry. Identity detectors run first; relation detectors get the alias table."""

from cairn.detectors.base import Detector
from cairn.detectors.database import DatabaseDetector
from cairn.detectors.docs import DocsDetector
from cairn.detectors.envvars import EnvVarsDetector
from cairn.detectors.http import HttpDetector
from cairn.detectors.identity import IdentityDetector
from cairn.detectors.infra import InfraDetector, is_compose_file
from cairn.detectors.messaging import MessagingDetector
from cairn.detectors.packages import PackagesDetector
from cairn.detectors.pathrefs import PathRefsDetector, is_config_file
from cairn.detectors.profile import ProfileDetector

IDENTITY_DETECTORS: tuple[Detector, ...] = (IdentityDetector(), ProfileDetector())
RELATION_DETECTORS: tuple[Detector, ...] = (
    PackagesDetector(),
    DatabaseDetector(),
    PathRefsDetector(),
    HttpDetector(),
    MessagingDetector(),
    InfraDetector(),
    EnvVarsDetector(),
    DocsDetector(),
)

# Detectors whose output depends on other repos (the alias table, which sibling paths
# exist, where this repo sits) and so always re-run instead of being cached per repo.
LIVE_DETECTOR_IDS = frozenset({"docs", "pathrefs", "infra"})
# The file filters live detectors walk with. A cached repo stores the files they match, so a
# warm refresh needn't walk it; any other filter falls back to a real walk.
LIVE_FILE_MATCHERS = (is_config_file, is_compose_file)
