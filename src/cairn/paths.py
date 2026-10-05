"""Locations of cairn's files inside a workspace."""

from pathlib import Path

CAIRN_DIR = ".cairn"


def cairn_dir(ws_root: Path) -> Path:
    return ws_root / CAIRN_DIR


def config_file(ws_root: Path) -> Path:
    return cairn_dir(ws_root) / "config.yaml"


def relations_file(ws_root: Path) -> Path:
    return cairn_dir(ws_root) / "relations.yaml"


def authored_dir(ws_root: Path) -> Path:
    return cairn_dir(ws_root) / "authored"


def workspace_file(ws_root: Path) -> Path:
    return cairn_dir(ws_root) / "workspace.json"


def cards_dir(ws_root: Path) -> Path:
    return cairn_dir(ws_root) / "cards"


def index_file(ws_root: Path) -> Path:
    return cairn_dir(ws_root) / "INDEX.md"


def backups_dir(ws_root: Path) -> Path:
    return cairn_dir(ws_root) / "cache" / "backups"
