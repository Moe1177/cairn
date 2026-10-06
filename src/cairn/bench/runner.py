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
    tools: tuple[tuple[str, int], ...] = ()  # (tool name, calls), sorted by name

    @property
    def fresh_tokens(self) -> int:
        """Tokens the model actually processed fresh (cache reads are near-free)."""
        return self.input_tokens + self.cache_creation_tokens + self.output_tokens


def parse_result(raw: str, stderr: str = "") -> RunResult:
    """claude's output: one JSON result (`--output-format json`), or a stream of JSON lines
    (`stream-json`) whose last `result` line holds the totals and whose assistant messages
    show each tool the agent called."""
    data, tools = _result_and_tools(raw)
    if data is None:  # no result: claude failed or stopped before answering
        text = f"{stderr.strip()}\n{raw}".strip() if stderr.strip() else raw
        return RunResult(
            result_text=text[-2000:], is_error=True, tools=tuple(sorted(tools.items()))
        )
    raw_usage = data.get("usage")
    usage: dict = raw_usage if isinstance(raw_usage, dict) else {}
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
        tools=tuple(sorted(tools.items())),
    )


def _result_and_tools(raw: str) -> tuple[dict | None, dict[str, int]]:
    try:
        single = json.loads(raw)
    except json.JSONDecodeError:
        single = None
    # A lone JSON object is `--output-format json`'s result, unless it is a stream's first event
    # (claude stopped right after `system/init`): that has a type, and no result.
    if isinstance(single, dict) and single.get("type") in (None, "result"):
        return single, {}
    result: dict | None = None
    tools: dict[str, int] = {}
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "result":
            result = event
        elif event.get("type") == "assistant":
            message = event.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    name = str(block.get("name") or "?")[:100]
                    tools[name] = tools.get(name, 0) + 1
    return result, tools


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

    def isolation_settings(self, ws: Path) -> dict[str, object]:
        """Keep the benchmarking user's own instructions out of every run.

        `--setting-sources project,local` doesn't cover memory files: ~/.claude/CLAUDE.md
        and ~/.claude/rules still load, as would a CLAUDE.md in any folder above the
        temporary workspace. Only the condition's workspace CLAUDE.md may load.
        """
        home = (self.home or claude_home()).as_posix().rstrip("/")
        above = [p.as_posix().rstrip("/") for p in ws.parents]
        excludes = [f"{home}/**"]
        excludes += [f"{d}/{name}" for d in above for name in ("CLAUDE.md", "CLAUDE.local.md")]
        excludes += [f"{d}/.claude/**" for d in above]
        return {"claudeMdExcludes": excludes, "autoMemoryEnabled": False}

    def command(self, prompt: str, ws: Path, mcp_config: Path | None) -> list[str]:
        # The resolved path, so npm's `claude.cmd` shim launches on Windows too.
        cmd = [
            shutil.which("claude") or "claude",
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--verbose",  # stream-json in print mode needs it; it adds each message to the stream
            "--model",
            self.model,
            "--setting-sources",
            "project,local",
            "--settings",
            json.dumps(self.isolation_settings(ws)),
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
        return parse_result(proc.stdout or proc.stderr, proc.stderr if proc.stdout else "")

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
