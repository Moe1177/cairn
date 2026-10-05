import json
import tomllib
from pathlib import Path

import pytest

from cairn.errors import CairnInputError
from cairn.integrations import config_files as cf

CMD = ["C:\\tools\\cairn.exe", "serve"]


@pytest.fixture(autouse=True)
def _homes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CAIRN_HOME", str(tmp_path / "cairn-home"))


def test_json_server_keeps_other_keys(tmp_path: Path) -> None:
    # Review Focus 1
    path = tmp_path / "settings.json"
    original = {"theme": "dark", "mcpServers": {"other": {"command": "x"}}}
    path.write_text(json.dumps(original), encoding="utf-8")
    cf.set_json_server(path, CMD, label="gemini")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["theme"] == "dark" and data["mcpServers"]["other"] == {"command": "x"}
    assert data["mcpServers"]["cairn"] == {"command": CMD[0], "args": ["serve"]}
    assert cf.remove_json_server(path, label="gemini") is True
    assert json.loads(path.read_text(encoding="utf-8")) == original
    assert cf.remove_json_server(path, label="gemini") is False
    assert (tmp_path / "cairn-home" / "backups" / "gemini-settings.json.orig").is_file()


def test_invalid_json_is_refused_untouched(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text("{oops", encoding="utf-8")
    with pytest.raises(CairnInputError):
        cf.set_json_server(path, CMD, label="cursor")
    assert path.read_text(encoding="utf-8") == "{oops"


def test_toml_server_block_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('model = "o4"\n', encoding="utf-8")
    cf.set_toml_server(path, CMD, label="codex")
    cf.set_toml_server(path, CMD, label="codex")  # idempotent
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parsed["mcp_servers"]["cairn"] == {"command": CMD[0], "args": ["serve"]}
    assert path.read_text(encoding="utf-8").count("# cairn:start") == 1
    assert cf.remove_toml_server(path, label="codex") is True
    assert path.read_text(encoding="utf-8") == 'model = "o4"\n'


def test_toml_refuses_foreign_cairn_table(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[mcp_servers.cairn]\ncommand = "mine"\n', encoding="utf-8")
    with pytest.raises(CairnInputError):
        cf.set_toml_server(path, CMD, label="codex")
    assert "mine" in path.read_text(encoding="utf-8")


def test_marker_text_and_owned_files(tmp_path: Path) -> None:
    agents = tmp_path / "AGENTS.md"
    cf.set_marker_text(agents, "pointer v1", label="codex")
    cf.set_marker_text(agents, "pointer v2", label="codex")
    assert "pointer v2" in agents.read_text(encoding="utf-8")
    assert cf.remove_marker_text(agents, label="codex") is True
    assert not agents.exists()
    skill = tmp_path / "skills" / "cairn" / "SKILL.md"
    cf.write_owned(skill, "body")
    assert cf.remove_owned(skill) is True
    assert not skill.parent.exists() and cf.remove_owned(skill) is False


def test_config_created_by_cairn_is_deleted_on_removal(tmp_path: Path) -> None:
    # Dogfood: uninstall left {"mcpServers": {}} files the user never had.
    path = tmp_path / "mcp.json"
    cf.set_json_server(path, CMD, label="cursor")
    assert cf.remove_json_server(path, label="cursor") is True
    assert not path.exists()
