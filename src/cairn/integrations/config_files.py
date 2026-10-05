"""Edit other tools' config files safely: only cairn's key/block, backups, refuse bad input.

Every editor validates the *result* before writing, keeps the file's BOM and newline style,
and turns unreadable files (not UTF-8, locked, permission denied) into a CairnInputError so
the caller can report it and move on to the next harness.
"""

import json
import stat
import tomllib
from pathlib import Path
from typing import Any

from cairn.errors import CairnInputError
from cairn.integrations.registry import cairn_home
from cairn.render.markers import START, TOML_END, TOML_START, remove_block, upsert_block
from cairn.store.atomic import atomic_write_text

SERVER_NAME = "cairn"
TOML_START_MARK = TOML_START
_BOM = "﻿"


def read_raw(path: Path) -> str:
    """Exact file text ('' if missing); unreadable files become CairnInputError."""
    if not path.is_file():
        return ""
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            return handle.read()
    except UnicodeDecodeError as exc:
        raise CairnInputError(str(path), "isn't UTF-8 text; left untouched") from exc
    except OSError as exc:
        raise CairnInputError(str(path), f"can't be read ({exc.strerror or exc})") from exc


def backup_once(path: Path, label: str) -> None:
    """Keep the user's original file once, before cairn's first edit."""
    if not path.is_file():
        return
    backups = cairn_home() / "backups"
    dest = backups / f"{label}-{path.name}.orig"
    if not dest.exists():
        backups.mkdir(parents=True, exist_ok=True, mode=0o700)  # config files can hold tokens
        source_mode = stat.S_IMODE(path.stat().st_mode)
        atomic_write_text(dest, read_raw(path), mode=source_mode & 0o700)


def _split_bom(raw: str) -> tuple[str, str]:
    return (_BOM, raw[1:]) if raw.startswith(_BOM) else ("", raw)


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _load_json(path: Path) -> tuple[dict[str, Any], str]:
    raw = read_raw(path)
    _, text = _split_bom(raw)
    try:
        data = json.loads(text) if text.strip() else {}
    except ValueError as exc:
        hint = " (comments aren't supported; add the cairn entry by hand)" if "//" in text else ""
        raise CairnInputError(str(path), f"invalid JSON ({exc}){hint}; left untouched") from exc
    servers = data.get("mcpServers", {}) if isinstance(data, dict) else None
    if not isinstance(data, dict) or not isinstance(servers, dict):
        raise CairnInputError(
            str(path), "expected an object with an 'mcpServers' object; left untouched"
        )
    return data, raw


def _dump_json(data: dict[str, Any], raw: str) -> str:
    bom, _ = _split_bom(raw)
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    return bom + text.replace("\n", _newline(raw)) if raw else text


def set_json_server(path: Path, command: list[str], *, label: str) -> None:
    data, raw = _load_json(path)
    entry = {"command": command[0], "args": command[1:]}
    servers = {**data.get("mcpServers", {}), SERVER_NAME: entry}
    backup_once(path, label)
    atomic_write_text(path, _dump_json({**data, "mcpServers": servers}, raw))


def remove_json_server(path: Path, *, label: str) -> bool:
    if not path.is_file():
        return False
    data, raw = _load_json(path)
    servers = data.get("mcpServers", {})
    if SERVER_NAME not in servers:
        return False
    rest = {k: v for k, v in servers.items() if k != SERVER_NAME}
    remaining = {**data, "mcpServers": rest}
    backup_once(path, label)
    if remaining == {"mcpServers": {}}:
        path.unlink()  # nothing but cairn's entry was ever in it
    else:
        atomic_write_text(path, _dump_json(remaining, raw))
    return True


def _parse_toml(path: Path, text: str) -> dict[str, Any]:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise CairnInputError(str(path), f"invalid TOML ({exc}); left untouched") from exc


def set_toml_server(path: Path, command: list[str], *, label: str) -> None:
    raw = read_raw(path)
    bom, text = _split_bom(raw)
    outside = remove_block(text, start=TOML_START, end=TOML_END)
    if SERVER_NAME in _parse_toml(path, outside).get("mcp_servers", {}):
        raise CairnInputError(
            str(path), "already defines [mcp_servers.cairn] outside cairn's block; left untouched"
        )
    # json.dumps output is a valid TOML basic string (Windows backslashes are escaped);
    # ensure_ascii=False because TOML rejects JSON's surrogate-pair escapes for emoji.
    body = (
        f"[mcp_servers.{SERVER_NAME}]\n"
        f"command = {json.dumps(command[0], ensure_ascii=False)}\n"
        f"args = {json.dumps(command[1:], ensure_ascii=False)}"
    )
    updated = upsert_block(text, body, start=TOML_START, end=TOML_END)
    expected = {"command": command[0], "args": command[1:]}
    try:
        valid = tomllib.loads(updated).get("mcp_servers", {}).get(SERVER_NAME) == expected
    except tomllib.TOMLDecodeError:
        valid = False
    if not valid:
        raise CairnInputError(
            str(path),
            "can't add [mcp_servers.cairn] without breaking this file (is mcp_servers an inline "
            f"table?); left untouched. Add it by hand:\n{body}",
        )
    backup_once(path, label)
    atomic_write_text(path, bom + updated)


def remove_toml_server(path: Path, *, label: str) -> bool:
    raw = read_raw(path)
    if TOML_START not in raw:
        return False
    bom, text = _split_bom(raw)
    backup_once(path, label)
    _write_or_delete(path, bom, remove_block(text, start=TOML_START, end=TOML_END))
    return True


def set_marker_text(path: Path, body: str, *, label: str) -> None:
    raw = read_raw(path)
    bom, text = _split_bom(raw)
    backup_once(path, label)
    atomic_write_text(path, bom + upsert_block(text, body))


def remove_marker_text(path: Path, *, label: str) -> bool:
    raw = read_raw(path)
    if START not in raw:
        return False
    bom, text = _split_bom(raw)
    backup_once(path, label)
    _write_or_delete(path, bom, remove_block(text))
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


def _write_or_delete(path: Path, bom: str, text: str) -> None:
    if text.strip():
        atomic_write_text(path, bom + text)
    else:
        path.unlink()
