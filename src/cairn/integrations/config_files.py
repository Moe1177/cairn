"""Edit other tools' config files safely: only cairn's key/block, backups, refuse bad input."""

import json
import tomllib
from pathlib import Path
from typing import Any

from cairn.errors import CairnInputError
from cairn.integrations.registry import cairn_home
from cairn.render.markers import START, TOML_END, TOML_START, remove_block, upsert_block
from cairn.store.atomic import atomic_write_text

SERVER_NAME = "cairn"
TOML_START_MARK = TOML_START


def read_raw(path: Path) -> str:
    if not path.is_file():
        return ""
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def backup_once(path: Path, label: str) -> None:
    """Keep the user's original file once, before cairn's first edit."""
    if not path.is_file():
        return
    dest = cairn_home() / "backups" / f"{label}-{path.name}.orig"
    if not dest.exists():
        atomic_write_text(dest, read_raw(path))


def _load_json(path: Path) -> dict[str, Any]:
    raw = read_raw(path)
    try:
        data = json.loads(raw) if raw.strip() else {}
    except ValueError as exc:
        raise CairnInputError(str(path), f"invalid JSON ({exc}); left untouched") from exc
    servers = data.get("mcpServers", {}) if isinstance(data, dict) else None
    if not isinstance(data, dict) or not isinstance(servers, dict):
        raise CairnInputError(
            str(path), "expected an object with an 'mcpServers' object; left untouched"
        )
    return data


def set_json_server(path: Path, command: list[str], *, label: str) -> None:
    data = _load_json(path)
    entry = {"command": command[0], "args": command[1:]}
    servers = {**data.get("mcpServers", {}), SERVER_NAME: entry}
    backup_once(path, label)
    atomic_write_text(path, json.dumps({**data, "mcpServers": servers}, indent=2) + "\n")


def remove_json_server(path: Path, *, label: str) -> bool:
    if not path.is_file():
        return False
    data = _load_json(path)
    servers = data.get("mcpServers", {})
    if SERVER_NAME not in servers:
        return False
    rest = {k: v for k, v in servers.items() if k != SERVER_NAME}
    backup_once(path, label)
    atomic_write_text(path, json.dumps({**data, "mcpServers": rest}, indent=2) + "\n")
    return True


def set_toml_server(path: Path, command: list[str], *, label: str) -> None:
    raw = read_raw(path)
    outside = remove_block(raw, start=TOML_START, end=TOML_END)
    try:
        parsed = tomllib.loads(outside)
    except tomllib.TOMLDecodeError as exc:
        raise CairnInputError(str(path), f"invalid TOML ({exc}); left untouched") from exc
    if SERVER_NAME in parsed.get("mcp_servers", {}):
        raise CairnInputError(
            str(path), "already defines [mcp_servers.cairn] outside cairn's block; left untouched"
        )
    # json.dumps output is a valid TOML basic string (Windows backslashes are escaped).
    body = (
        f"[mcp_servers.{SERVER_NAME}]\n"
        f"command = {json.dumps(command[0])}\n"
        f"args = {json.dumps(command[1:])}"
    )
    backup_once(path, label)
    atomic_write_text(path, upsert_block(raw, body, start=TOML_START, end=TOML_END))


def remove_toml_server(path: Path, *, label: str) -> bool:
    raw = read_raw(path)
    if TOML_START not in raw:
        return False
    backup_once(path, label)
    _write_or_delete(path, remove_block(raw, start=TOML_START, end=TOML_END))
    return True


def set_marker_text(path: Path, body: str, *, label: str) -> None:
    raw = read_raw(path)
    backup_once(path, label)
    atomic_write_text(path, upsert_block(raw, body))


def remove_marker_text(path: Path, *, label: str) -> bool:
    raw = read_raw(path)
    if START not in raw:
        return False
    backup_once(path, label)
    _write_or_delete(path, remove_block(raw))
    return True


def write_owned(path: Path, text: str) -> None:
    """Write a file cairn fully owns (skills, commands, rules)."""
    atomic_write_text(path, text)


def remove_owned(path: Path) -> bool:
    if not path.is_file():
        return False
    path.unlink()
    if path.parent.is_dir() and not any(path.parent.iterdir()):
        path.parent.rmdir()
    return True


def _write_or_delete(path: Path, text: str) -> None:
    if text.strip():
        atomic_write_text(path, text)
    else:
        path.unlink()
