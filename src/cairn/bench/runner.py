"""Run one benchmark prompt through a headless agent (spec §11 E2).

ClaudeRunner drives `claude -p` in an isolated, read-only session: user settings and
memory are not loaded (`--setting-sources project,local`), only the MCP servers in the
condition's config are visible (`--strict-mcp-config`), and only read tools are allowed
(no shell: even `find` can delete or run programs through `-delete`/`-exec`).
"""

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

READ_ONLY_TOOLS = ("Read", "Grep", "Glob", "mcp__cairn")


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
    models: tuple[str, ...] = ()

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
    model_usage = data.get("modelUsage")
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
        models=tuple(sorted(model_usage)) if isinstance(model_usage, dict) else (),
    )


def claude_home() -> Path:
    """Claude Code's config folder (the user's real one: benchmarks only clean up after runs)."""
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(override) if override else Path.home() / ".claude"


def project_slug(cwd: Path) -> str:
    """How Claude Code names a working directory's folder under `projects/`."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(cwd))


def forget_project(home: Path, cwd: Path) -> None:
    """Remove the per-cwd folder a headless run leaves behind, if it holds no files."""
    target = home / "projects" / project_slug(cwd)
    if target.is_dir() and not any(p.is_file() for p in target.rglob("*")):
        shutil.rmtree(target, ignore_errors=True)


class Runner(Protocol):
    def run(self, prompt: str, cwd: Path, ws: Path, mcp_config: Path | None) -> RunResult: ...


@dataclass(frozen=True)
class ClaudeRunner:
    model: str = "haiku"
    timeout: float = 900.0
    home: Path | None = None  # Claude Code's config folder; default claude_home()

    def command(self, prompt: str, ws: Path, mcp_config: Path | None) -> list[str]:
        # The resolved path, so npm's `claude.cmd` shim launches on Windows too.
        cmd = [
            shutil.which("claude") or "claude",
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
        finally:
            home = self.home or claude_home()
            for path in {cwd, cwd.resolve()}:
                forget_project(home, path)
        return parse_result(proc.stdout or proc.stderr)

    def version(self) -> str:
        try:
            done = subprocess.run(
                [shutil.which("claude") or "claude", "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return "unknown"
        return done.stdout.strip() or "unknown"


@dataclass(frozen=True)
class FakeRunner:
    """Test double: `reply(prompt, cwd)` returns the raw JSON claude would print."""

    reply: Callable[[str, Path], str]

    def run(self, prompt: str, cwd: Path, ws: Path, mcp_config: Path | None) -> RunResult:
        return parse_result(self.reply(prompt, cwd))
