"""Run one benchmark prompt through a headless agent (spec §11 E2).

ClaudeRunner drives `claude -p` in an isolated, read-only session: user settings and
memory are not loaded (`--setting-sources project,local`), only the MCP servers in the
condition's config are visible (`--strict-mcp-config`), and only read tools are allowed.
"""

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

READ_ONLY_TOOLS = (
    "Read",
    "Grep",
    "Glob",
    "Bash(ls:*)",
    "Bash(cat:*)",
    "Bash(find:*)",
    "mcp__cairn",
)


@dataclass(frozen=True)
class RunResult:
    result_text: str
    num_turns: int = 0
    cost_usd: float = 0.0
    input_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0
    is_error: bool = False

    @property
    def fresh_tokens(self) -> int:
        """Tokens the model actually processed fresh (cache reads are near-free)."""
        return self.input_tokens + self.cache_creation_tokens + self.output_tokens


def parse_result(raw: str) -> RunResult:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return RunResult(result_text=raw[-2000:], is_error=True)
    if not isinstance(data, dict):
        return RunResult(result_text=raw[-2000:], is_error=True)
    usage = data.get("usage") or {}
    return RunResult(
        result_text=str(data.get("result") or ""),
        num_turns=int(data.get("num_turns") or 0),
        cost_usd=float(data.get("total_cost_usd") or 0.0),
        input_tokens=int(usage.get("input_tokens") or 0),
        cache_creation_tokens=int(usage.get("cache_creation_input_tokens") or 0),
        cache_read_tokens=int(usage.get("cache_read_input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        duration_ms=int(data.get("duration_ms") or 0),
        is_error=bool(data.get("is_error")),
    )


class Runner(Protocol):
    def run(self, prompt: str, cwd: Path, ws: Path, mcp_config: Path | None) -> RunResult: ...


@dataclass(frozen=True)
class ClaudeRunner:
    model: str = "haiku"
    timeout: float = 900.0

    def command(self, prompt: str, ws: Path, mcp_config: Path | None) -> list[str]:
        cmd = [
            "claude",
            "-p",
            prompt,
            "--output-format",
            "json",
            "--model",
            self.model,
            "--setting-sources",
            "project,local",
            "--no-session-persistence",
            "--permission-mode",
            "dontAsk",
            "--allowedTools",
            *READ_ONLY_TOOLS,
            "--add-dir",
            str(ws),
            "--strict-mcp-config",
        ]
        if mcp_config is not None:
            cmd += ["--mcp-config", str(mcp_config)]
        return cmd

    def run(self, prompt: str, cwd: Path, ws: Path, mcp_config: Path | None) -> RunResult:
        try:
            proc = subprocess.run(
                self.command(prompt, ws, mcp_config),
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return RunResult(result_text=f"runner error: {exc}", is_error=True)
        return parse_result(proc.stdout or proc.stderr)


@dataclass(frozen=True)
class FakeRunner:
    """Test double: `reply(prompt, cwd)` returns the raw JSON claude would print."""

    reply: Callable[[str, Path], str]

    def run(self, prompt: str, cwd: Path, ws: Path, mcp_config: Path | None) -> RunResult:
        return parse_result(self.reply(prompt, cwd))
