# cairn

[![PyPI](https://img.shields.io/pypi/v/cairnmap)](https://pypi.org/project/cairnmap/)
[![Python](https://img.shields.io/pypi/pyversions/cairnmap)](https://pypi.org/project/cairnmap/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

> Cairns are the stacked-stone markers that guide hikers along a trail. cairn leaves small, cheap
> markers that guide coding agents to the right repo, and then to the right file.

Mention a repo that isn't in your agent's working directory, and the agent usually doesn't know
what you mean, so it explores, greps, and burns tokens. cairn maps every git repo under a folder
once. It then gives your agent two things:
- a tiny always-loaded index;
- one short card per repo, read on demand, covering what the repo is, how it connects to the
  others, and where to look.

It works with Claude Code, Codex, Gemini CLI, and Cursor, on Windows, macOS, and Linux.

## Quick start

```bash
cd ~/code                              # the folder that contains your repos
uvx --from cairnmap cairn init         # or: pipx install cairnmap / uv tool install cairnmap
```

`cairn init` scans every git repo under the folder, writes `.cairn/`, and offers to add the index
to `CLAUDE.md` in that folder. Claude Code reads parent `CLAUDE.md` files, so every repo inside now
knows about its siblings. For other agents, run `cairn install all` (see
[Use it from any agent](#use-it-from-any-agent)).

Requirements: Python 3.11+ and git.

## What it finds

cairn links repos through:
- **Package dependencies:** npm, PyPI, Go modules, Cargo.
- **Shared database tables:** SQL migrations and queries, Prisma, Drizzle, and Supabase.
- **`../` path references** in configs such as docker-compose and tsconfig.
- **Docs that mention a sibling repo.**

Each relationship is tagged `extracted`, `inferred`, or `ambiguous`, so the agent knows how far to
trust it. Unconfirmed links are hidden from cards until you settle them:

```bash
cairn status                                                   # lists unconfirmed links
cairn annotate-edge "web->api:shares_db" --confirm
cairn annotate-edge "shop->blog:shares_db" --reject --why "different databases"
```

Decisions are stored in `.cairn/authored/` and survive every re-scan.

## Commands

| Command | What it does |
|---|---|
| `cairn init` | Scan, then offer to add the index to Claude Code |
| `cairn scan [--full] [--verbose]` | Map every repo under the folder into `.cairn/` |
| `cairn refresh` | Re-read only repos whose HEAD or working tree changed |
| `cairn status` | What cairn knows, unconfirmed links, and missing or stale summaries |
| `cairn annotate-edge KEY --confirm\|--reject [--why TEXT]` | Settle a relationship |
| `cairn set-summary REPO TEXT [--alias NAME]` | Save a one- or two-sentence summary (`-` reads stdin) |
| `cairn install <claude\|codex\|gemini\|cursor\|all>` | Load cairn into an agent harness |
| `cairn uninstall <name\|all>` | Remove it again |
| `cairn hooks install\|uninstall` | Opt-in git hooks that refresh after commits and merges |
| `cairn serve` | The MCP server (harnesses start it for you) |
| `cairn bench SUITE` | Measure what the map saves (see [Benchmarks](#benchmarks)) |
| `cairn --version` | Versions of cairn, Python, the platform, and mcp |

## Use it from any agent

```bash
cairn install claude     # index in the folder's CLAUDE.md, /cairn skill, MCP server (user scope)
cairn install codex      # pointer in ~/.codex/AGENTS.md, skill, [mcp_servers.cairn]
cairn install gemini     # pointer in ~/.gemini/GEMINI.md, /cairn command, mcpServers.cairn
cairn install cursor     # /cairn command, ~/.cursor/mcp.json (--per-repo adds git-excluded rules)
cairn install all        # all of the above; one broken config doesn't stop the rest
```

cairn only edits its own key or marked block in those files, backs each file up once to
`~/.cairn/backups/`, and refuses to touch a file it can't parse.

**MCP tools.** `resolve_repo`, `repo_card`, `related`, `find_across`, `query`, and `refresh`.
- Every answer is capped.
- A repo whose HEAD moved is re-scanned before its card is returned.
- While another scan is running, tools answer from the last map within a few seconds.

**Summaries.** Run `/cairn` in your agent. It reads `cairn status`, writes a short summary for each
repo with `cairn set-summary`, and settles unconfirmed links. Until a repo has a summary, its index
line says "no summary yet". README text never goes into always-loaded context.

## Freshness

Each repo's results are cached against:
- its HEAD,
- a working-tree fingerprint, and
- the cairn config.

So refreshing an unchanged workspace is near-instant. `cairn hooks install` adds a background
refresh after each commit and merge. It goes in a marked block next to any hook you already have,
and `cairn hooks uninstall` restores the original byte for byte. It skips non-shell hooks and repos
managed by husky or lefthook (`core.hooksPath`), and tells you which ones it skipped. When a repo has
changed a lot since its summary was written, its card flags the summary as possibly stale.

## What cairn writes, and where

| Path | What it is |
|---|---|
| `<folder>/.cairn/INDEX.md` | One line per repo (~25 tokens): name, aliases, summary, stack |
| `<folder>/.cairn/cards/<repo>.md` | A card of at most 800 tokens: summary, run commands, layout, relationships with evidence |
| `<folder>/.cairn/workspace.json` | The full graph |
| `<folder>/.cairn/cache/`, `logs/`, `.lock` | Per-repo scan cache, last scan log, lock file |
| `<folder>/.cairn/relations.yaml` | **Yours:** extra aliases, manual links, notes, ignored repos |
| `<folder>/.cairn/authored/<repo>.yaml` | **Yours:** summaries and link decisions |
| `<folder>/CLAUDE.md` | A marked block holding the index (`cairn install claude`) |
| `~/.claude/skills/cairn/`, Claude's user MCP config | `/cairn` skill and MCP server |
| `~/.codex/AGENTS.md`, `config.toml`, `skills/cairn/` | Codex pointer, MCP server, skill |
| `~/.gemini/GEMINI.md`, `settings.json`, `commands/cairn.toml` | Gemini CLI pointer, MCP server, command |
| `~/.cursor/mcp.json`, `commands/cairn.md` | Cursor MCP server and command |
| `<repo>/.git/hooks/post-commit`, `post-merge` | Only with `cairn hooks install` |
| `~/.cairn/registry.json`, `backups/` | Mapped workspaces; one backup of each file cairn first edited |

Commit `.cairn/relations.yaml` and `.cairn/authored/` if you want to share decisions with your
team; the rest is generated.

## Uninstall

```bash
cairn uninstall all          # harness entries, skills, commands, Cursor rules
cairn hooks uninstall        # if you installed hooks
pipx uninstall cairnmap      # or: uv tool uninstall cairnmap
```

Then delete `<folder>/.cairn/` and `~/.cairn/`.

## Safety

cairn treats every scanned repo as untrusted input. It:
- **never** modifies your repos, apart from the opt-in hooks and Cursor's `--per-repo` rule;
- **never** follows symlinks or junctions out of a repo;
- **never** opens `.env` files, private keys, or credential files;
- **never** runs code from a repo; its git calls turn off fsmonitor, hooks, and the repo's own
  filters.

Every stored snippet is redacted for common secret formats, and git remotes are stored without
credentials. README text stays out of always-loaded context. The names that do appear there are
flattened to one line and capped, and can't break out of cairn's marked blocks. cairn makes **no network calls and collects no telemetry**; `cairn bench` is the only
feature that runs another program that does (the `claude` CLI).

See [SECURITY.md](SECURITY.md) for the full threat model and how to report a vulnerability.

## Benchmarks

`cairn bench` runs each task in a suite through headless Claude Code under five conditions, each
in a fresh copy of the suite's workspace:

| | Condition |
|---|---|
| A | No map |
| B | A hand-written `RELATED_REPOS`-style doc as CLAUDE.md |
| C | cairn's index only |
| D | Index + repo cards |
| E | D + cairn's MCP server |

Runs are isolated. The agent only has read-only tools (Read, Grep, Glob, plus cairn's MCP tools in
E), and your own CLAUDE.md, rules, memory, and MCP servers are never loaded.

Answers are graded deterministically:
- **Localization and impact tasks:** recall of the files that must change (pass at 80%).
- **Orientation tasks:** required keywords.

Reports go to `bench/results/`, with every finished run appended immediately.

```bash
# from a source checkout (uses your Claude usage)
cairn bench bench/suites/fleetline --runs 3 --model haiku
cairn bench bench/suites/shopverse --conditions A,D --tasks gift-message
```

**First results** ([full tables](bench/published/2026-10-05-shopverse-fleetline.md); 3 runs per
cell on small synthetic workspaces, so treat them as direction, not proof):
- **Accuracy.** With cairn's index, Haiku answered every task correctly on both suites. With no
  map it missed 4–11%.
- **Cost.** The effect is small at this scale: −42% to +6% against no map, depending on the model
  and condition. Strong models with grep explore a 6–15 repo workspace in about 4 turns. Larger
  workspaces are the next benchmark.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "No git repos found under …" | Run cairn from the folder that *contains* your repos |
| "… is inside the git repository …" | Same: run from the parent folder, not inside a repo |
| "git not found on PATH" warning | Install git; without it, remotes, HEAD and caching are off |
| "another cairn process is still updating this workspace" | A scan or hook refresh is running; retry in a moment |
| An agent says it can't find the workspace | Run `cairn init` in the workspace folder, then restart the agent session |
| `cairn install codex/gemini/cursor` refuses a config | That file isn't valid TOML/JSON; fix it and re-run (cairn never guesses) |
| Hooks did nothing | `cairn hooks install` lists the repos it skipped and why (non-shell hook, `core.hooksPath`) |

**Exit codes:** `0` means success, `1` an error (one line on stderr), and `2` a usage error.

## Roadmap

1. Core map, precision pass, harness integrations, freshness, benchmarks, release hardening
   (**done**, 0.1).
2. HTTP, infra and environment-variable relationships, and packages inside monorepos.
3. Deep per-repo queries via [graphify](https://github.com/Graphify-Labs/graphify).
4. Larger benchmark suites (open-source workspaces), significance testing, and more harnesses.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CHANGELOG.md](CHANGELOG.md). By participating you
agree to the [code of conduct](CODE_OF_CONDUCT.md).

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
