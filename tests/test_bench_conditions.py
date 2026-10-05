import json
from pathlib import Path

import pytest

from cairn.bench.conditions import prepare
from cairn.bench.suite import load_suite

SUITE = Path(__file__).resolve().parents[1] / "bench" / "suites" / "shopverse"


@pytest.fixture(autouse=True)
def _homes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CAIRN_HOME", str(tmp_path / "ch"))
    monkeypatch.setenv("CAIRN_USER_HOME", str(tmp_path / "uh"))


@pytest.mark.parametrize("cond", ["A", "B", "C", "D", "E"])
def test_condition_isolation(cond: str, tmp_path: Path) -> None:
    # Review Focus 5
    prepared = prepare(cond, load_suite(SUITE), SUITE, tmp_path / cond)
    ws = prepared.ws
    claude_md = ws / "CLAUDE.md"
    if cond == "A":
        assert not claude_md.exists() and not (ws / ".cairn").exists()
    if cond == "B":
        assert "orders-svc" in claude_md.read_text(encoding="utf-8")
        assert not (ws / ".cairn").exists()
    if cond in "CDE":
        assert "<!-- cairn:start -->" in claude_md.read_text(encoding="utf-8")
        assert (ws / ".cairn" / "cards").is_dir() == (cond != "C")
    if cond == "E":
        assert prepared.mcp_config is not None
        cfg = json.loads(prepared.mcp_config.read_text(encoding="utf-8"))
        assert cfg["mcpServers"]["cairn"]["args"][-2:] == ["--workspace", ws.as_posix()]
    else:
        assert prepared.mcp_config is None
