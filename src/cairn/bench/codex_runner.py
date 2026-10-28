"""Run one benchmark prompt through Codex (`codex exec`), isolated like ClaudeRunner.

Runs ignore the user's Codex config and rules (`--ignore-user-config`, `--ignore-rules`) and
turn off every tool beyond reading the workspace (connected apps, plugins, web search, browsers,
hooks, sub-agents), so nothing of theirs and nothing from the network reaches a run; only the Windows sandbox mode is
carried over, since without it the sandbox blocks every command. The condition's context (the
workspace CLAUDE.md that conditions B-E write) is given as developer instructions, which Codex
reads in every turn, the way a Codex user would get cairn's index. The sandbox is read-only and
approvals are off: the agent can read the whole workspace and change nothing. Sessions are not
saved (`--ephemeral`).

Codex has no switch for its global AGENTS.md, and Windows' elevated sandbox can't be set up in a
throwaway CODEX_HOME, so a run uses the user's own home: if it holds an AGENTS.md (where
`cairn install codex` puts its pointer), the benchmark refuses to start rather than let it reach
every condition.
"""

import json
import shutil
import subprocess
import time
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from cairn.bench.runner import RunResult
from cairn.errors import CairnError
from cairn.integrations.homes import codex_home

CONTEXT_FILE = "CLAUDE.md"  # what conditions B-E write at the workspace root
GLOBAL_INSTRUCTIONS = ("AGENTS.md", "AGENTS.override.md")
# Tools beyond reading the workspace: connected apps (a GitHub search answers from the network),
# plugins, browsers, hooks, sub-agents. ClaudeRunner allows only Read, Grep, Glob and cairn.
DISABLED_FEATURES = (
    "apps",
    "plugins",
    "remote_plugin",
    "browser_use",
    "browser_use_external",
    "computer_use",
    "image_generation",
    "hooks",
    "multi_agent",
    "tool_suggest",
    "skill_mcp_dependency_install",
)


def parse_codex_result(raw: str, stderr: str = "", *, model: str | None = None) -> RunResult:
    """`codex exec --json` prints one event per line: the answer is the last agent message, and
    each finished turn reports its tokens (input counts cached input, which is near-free)."""
    answer = ""
    error = ""
    tools: dict[str, int] = {}
    total = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        item = event.get("item")
        if kind == "item.completed" and isinstance(item, dict):
            answer = _item(item, tools) or answer
        elif kind == "turn.completed" and isinstance(event.get("usage"), dict):
            for key in total:
                total[key] += int(event["usage"].get(key) or 0)
        elif kind in ("turn.failed", "error"):
            error = _message(event) or error
    if error or not answer:
        text = "\n".join(p for p in (error, stderr.strip()[-1000:]) if p) or "codex gave no answer"
        return RunResult(result_text=text, is_error=True, tools=tuple(sorted(tools.items())))
    cached = total["cached_input_tokens"]
    return RunResult(
        result_text=answer,
        num_turns=sum(tools.values()),
        input_tokens=max(0, total["input_tokens"] - cached),
        cache_read_tokens=cached,
        output_tokens=total["output_tokens"],
        models=(model,) if model else (),
        tools=tuple(sorted(tools.items())),
    )


def _item(item: dict, tools: dict[str, int]) -> str | None:
    """The agent's message text, after counting the tool an item used (if any)."""
    kind = item.get("type")
    if kind == "agent_message":
        return str(item.get("text") or "") or None
    if kind == "command_execution":
        tools["shell"] = tools.get("shell", 0) + 1
    elif kind == "mcp_tool_call":
        name = f"mcp__{item.get('server') or '?'}__{item.get('tool') or '?'}"[:100]
        tools[name] = tools.get(name, 0) + 1
    elif isinstance(kind, str) and kind not in ("reasoning", "todo_list"):
        tools[kind[:100]] = tools.get(kind[:100], 0) + 1
    return None


def _message(event: dict) -> str:
    error = event.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or "")[:1000]
    return str(event.get("message") or "")[:1000]


@dataclass(frozen=True)
class CodexRunner:
    model: str | None = None  # None: Codex's own default
    timeout: float = 900.0
    home: Path | None = None  # the user's CODEX_HOME; default codex_home()

    def check(self) -> None:
        """Refuse a home whose global instructions would reach every condition."""
        home = self.home or codex_home()
        found = [home / name for name in GLOBAL_INSTRUCTIONS if (home / name).is_file()]
        if found:
            raise CairnError(
                f"{found[0]} would load into every benchmark run (Codex can't skip it), so "
                "condition A wouldn't be cold. Move it aside while benchmarking (`cairn "
                "uninstall codex` removes cairn's pointer), then run again."
            )

    def command(
        self,
        prompt: str,
        cwd: Path,
        mcp_config: Path | None,
        *,
        instructions: str | None = None,
        carried: tuple[str, ...] = (),
    ) -> list[str]:
        cmd = [
            *codex_program(),
            "exec",
            "--json",
            "--ephemeral",
            "--skip-git-repo-check",
            "--ignore-user-config",
            "--ignore-rules",
            "--sandbox",
            "read-only",
            "-c",
            'approval_policy="never"',
            "-c",
            'web_search="disabled"',
            *(flag for feature in DISABLED_FEATURES for flag in ("--disable", feature)),
            "-C",
            str(cwd),
        ]
        if self.model:
            cmd += ["--model", self.model]
        if instructions:
            cmd += ["-c", f"developer_instructions={json.dumps(instructions)}"]
        cmd += _mcp_flags(mcp_config)
        for setting in carried:
            cmd += ["-c", setting]
        return [*cmd, prompt]

    def run(
        self,
        prompt: str,
        cwd: Path,
        ws: Path,
        mcp_config: Path | None,
        hidden: Sequence[Path] = (),
    ) -> RunResult:
        """`hidden` can't be kept from Codex: its read-only sandbox reads the whole disk, through
        a shell. So `cairn bench --scope repo`, which relies on it, refuses Codex."""
        self.check()
        context = ws / CONTEXT_FILE
        instructions = context.read_text(encoding="utf-8") if context.is_file() else None
        carried = carried_settings(self.home or codex_home())
        started = time.monotonic()
        try:
            proc = subprocess.run(
                self.command(prompt, cwd, mcp_config, instructions=instructions, carried=carried),
                cwd=cwd,
                stdin=subprocess.DEVNULL,  # else codex waits to append stdin to the prompt
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return RunResult(result_text=f"runner error: {exc}", is_error=True)
        result = parse_codex_result(proc.stdout or "", proc.stderr or "", model=self.model)
        duration = int((time.monotonic() - started) * 1000)
        return RunResult(**{**result.__dict__, "duration_ms": duration})

    def version(self) -> str:
        try:
            done = subprocess.run(
                [*codex_program(), "--version"],
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


def codex_program() -> list[str]:
    """How to start Codex. npm's Windows shim (`codex.cmd`) runs through cmd.exe, which reads
    `<` and `>` in an argument (the index's `<repo>`) as redirections: run its script with node
    instead, as the shim itself does."""
    found = shutil.which("codex") or "codex"
    if found.lower().endswith((".cmd", ".bat")):
        script = Path(found).parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
        node = shutil.which("node")
        if script.is_file() and node:
            return [node, str(script)]
    return [found]


def carried_settings(real: Path) -> tuple[str, ...]:
    """The few user settings a run needs to work at all, as `-c` overrides: on Windows, the
    sandbox mode Codex was set up with (without it, the read-only sandbox blocks every command)."""
    try:
        config = tomllib.loads((real / "config.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return ()
    windows = config.get("windows")
    mode = windows.get("sandbox") if isinstance(windows, dict) else None
    return (f"windows.sandbox={json.dumps(mode)}",) if isinstance(mode, str) else ()


def _mcp_flags(mcp_config: Path | None) -> list[str]:
    """The condition's MCP server (Claude's mcp.json shape) as Codex `-c` overrides."""
    if mcp_config is None:
        return []
    servers = json.loads(mcp_config.read_text(encoding="utf-8")).get("mcpServers", {})
    flags: list[str] = []
    for name, entry in servers.items():
        flags += ["-c", f"mcp_servers.{name}.command={json.dumps(entry['command'])}"]
        flags += ["-c", f"mcp_servers.{name}.args={json.dumps(entry.get('args', []))}"]
    return flags
