# cairn

[![CI](https://github.com/Moe1177/cairn/actions/workflows/ci.yml/badge.svg)](https://github.com/Moe1177/cairn/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/cairnmap)](https://pypi.org/project/cairnmap/)
[![Python](https://img.shields.io/pypi/pyversions/cairnmap)](https://pypi.org/project/cairnmap/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/Moe1177/cairn/blob/main/LICENSE)

**A map of all your repos for coding agents.** cairn scans every git repo in a folder once, works
out how they connect, and gives your agent:
- a tiny always-loaded index;
- a short card per repo.

The agent knows where things live without re-exploring.

> Cairns are the stacked-stone markers that guide hikers along a trail. cairn leaves small, cheap
> markers that guide coding agents to the right repo, and then to the right file.

Works with **Claude Code, Codex, Gemini CLI, and Cursor**, on **Windows, macOS, and Linux**.

---

## Why

Coding agents work inside one repo. Real work spans many: a web app, an API, a shared types
package, a payments service, a reporting job. Say *"add a tip amount to trips end to end"* and the
agent has to:
1. discover that sibling repos exist;
2. grep through all of them;
3. read a pile of files;
4. guess which service owns the `trips` table.

That costs tokens and turns, and weaker models guess wrong.

Hand-maintained "related repos" docs help until they go stale. cairn builds that map from the code
itself and keeps it fresh:

```
~/code/                          ~/code/.cairn/
├── rider-web/        cairn      ├── INDEX.md           ← ~25 tokens per repo, always loaded
├── trips-svc/        ─────▶     ├── cards/trips-svc.md ← read on demand (≤ 800 tokens)
├── payments-svc/     scan       ├── workspace.json     ← the full graph
├── analytics-etl/               └── authored/          ← your summaries and decisions
└── …
```

## What your agent sees

The **index** is a few lines, loaded into every session through `CLAUDE.md` or an equivalent:

```markdown
# Workspace repos (cairn)
- admin-console (@fleetline/admin-console): Next.js back-office for ops staff; queries trips… · nextjs
- analytics-etl: Nightly SQL reporting jobs over trips, payments, drivers… · python
- payments-svc (payments): Go service that charges completed trips and records weekly payouts · go
- trips-svc: FastAPI service owning the trip lifecycle and the trips/trip_events tables · fastapi
- ui-kit (@fleetline/ui-kit): Shared React components (Button, Card) · react
```

A **card** is read only when the agent needs that repo:

```markdown
# trips-svc
> FastAPI service owning the trip lifecycle and the trips/trip_events tables.
`./trips-svc` · python, fastapi · HEAD 1fee22d

## Relates
← infra: references path trips-svc (extracted · infra/docker-compose.dev.yml:3)
→ admin-console: shares tables trips (inferred · admin-console/lib/db.ts:4)
→ analytics-etl: shares tables trips (inferred · analytics-etl/jobs/daily_revenue.sql:2)
→ payments-svc: shares tables trips (inferred · payments-svc/internal/charge/charge.go:3)

## Run
test `pytest`

## Layout
app/ → routes/pages
migrations/ → DB migrations
```

Every relationship comes with evidence (file and line) and a trust level:
- `extracted`: found directly, such as a package dependency or a path reference;
- `inferred`: strong signals, such as a table that only one repo creates;
- `ambiguous`: hidden until you confirm it.

## Install

You need Python 3.11+ and git.

| Tool | Command |
|---|---|
| [uv](https://docs.astral.sh/uv/) (recommended) | `uv tool install cairnmap` |
| pipx | `pipx install cairnmap` |
| run once, no install | `uvx --from cairnmap cairn init` |
| pip | `pip install cairnmap` |

The package is called `cairnmap`; the command is `cairn`.

## Quick start

```bash
cd ~/code              # the folder that CONTAINS your repos
cairn init             # scan, then add the index to ./CLAUDE.md (asks first)
cairn install all      # optional: Codex, Gemini CLI, Cursor, the /cairn skill, the MCP server
```

Open your agent in any repo under that folder. It now knows about every sibling repo.

To give each repo a good one-line summary, run `/cairn` inside your agent. It writes the summaries
with `cairn set-summary` and settles uncertain links. Until then, the index says "no summary yet"
for that repo. README text is deliberately kept out of always-loaded context.

## How to use it

### Day to day

```bash
cairn status               # repos, relationships, unconfirmed links, missing/stale summaries
cairn refresh              # re-read only repos that changed (fast)
cairn hooks install        # optional: refresh automatically after each commit/merge
```

### Settle uncertain links once

```bash
cairn annotate-edge "web->api:shares_db" --confirm
cairn annotate-edge "shop->blog:shares_db" --reject --why "different databases"
cairn set-summary payments-svc "Charges completed trips and pays drivers weekly." --alias payments
```

These decisions live in `.cairn/authored/` and `.cairn/relations.yaml`. They survive every re-scan,
and you can commit them so your team shares them.

### From your agent (MCP)

`cairn install <harness>` registers cairn's MCP server. Agents can call these tools:

| Tool | What it answers |
|---|---|
| `resolve_repo` | "Which repo is 'the payments service'?" |
| `repo_card` | The card for a repo (re-scanned first if its HEAD moved) |
| `related` | Everything connected to a repo, with evidence |
| `find_across` | Which repos expose or use a table, package, or path |
| `query` | Where to start looking inside a repo |
| `refresh` | Update the map now |

### What cairn detects

| Signal | Examples |
|---|---|
| HTTP calls | Next.js routes, Express/Fastify/Hono, FastAPI/Flask, Go (net/http, chi, gin, echo) and OpenAPI routes, matched with `fetch`/`axios`, `requests`/`httpx`, and Go `http` client calls |
| gRPC | Go, Python, TypeScript and Java servers matched with their client stubs |
| Pub/sub topics | Kafka, NATS and Redis publishers matched with subscribers (`trip.completed`) |
| docker-compose | `depends_on` between services built from (or named after) your repos |
| Package dependencies | npm (`workspace:*`, scoped packages), PyPI, Go modules, Cargo |
| Packages inside monorepos | npm/yarn/pnpm, Cargo, `go.work` and uv workspaces, listed on the card and resolvable by name |
| Shared database tables | SQL migrations and queries, Prisma, Drizzle, Supabase |
| Path references | `../trips-svc` in docker-compose, tsconfig, and other config files |
| Documentation | READMEs and docs that mention a sibling repo |
| Shared env vars | Specific names read by both sides. These only back up another link; they never make one on their own |

Look-alikes are deliberately ignored:
- health-check routes;
- calls to other companies' APIs;
- vague topic names;
- `.proto` files with no implementer;
- generic env vars such as `PORT`.

An evaluation workspace in the test suite keeps every one of these at precision 1.0.

## Benchmarks

cairn ships a benchmark harness (`cairn bench`). It runs real tasks through headless Claude Code
under five conditions, each in a fresh, isolated copy of a multi-repo workspace:

| | Condition |
|---|---|
| **A** | No map (the agent explores) |
| **B** | A hand-written "related repos" doc |
| **C** | cairn's index only |
| **D** | Index + repo cards |
| **E** | D + cairn's MCP server |

Tasks cover:
- **orientation:** "who owns the trips table?";
- **localization:** "which files change to add a tip amount end to end?";
- **cross-repo impact:** "what breaks if `drivers.license_no` is renamed?";
- **control:** questions answerable within one repo.

Answers are graded deterministically on the files and facts they must name.

**First results** on two synthetic workspaces, `shopverse` (6 repos) and `fleetline` (15 repos):

| | Haiku 4.5 | Sonnet 5.5 | Opus 5.5 |
|---|---|---|---|
| Success, no map (A) | 89–96% | 100% | 100% |
| Success, cairn index (C) | **100%** | **100%** | **100%** |
| Best cairn cost vs no map | **−42%** (D) | **−24%** (C) | **−7%** (C) |

What this shows so far:
- **Weaker models gain accuracy.** Haiku went from missing 4–11% of tasks to 100%.
- **The index alone is the most reliable condition** on every model and suite.
- **Cost savings are modest on small workspaces.** Strong models with grep explore 6–15 small repos
  in about 4 turns, and cairn's savings should grow with workspace size. These are first results:
  3 runs per cell, no significance testing yet. The Opus runs cover shopverse only.

Full tables, model ids, and caveats:
[bench/published](https://github.com/Moe1177/cairn/blob/main/bench/published/2026-10-05-shopverse-fleetline.md).

Run the benchmarks yourself from a source checkout. They use your Claude usage.

```bash
cairn bench bench/suites/fleetline --runs 3 --model haiku
cairn bench bench/suites/shopverse --conditions A,C --tasks gift-message
```

## Safety and privacy

cairn treats every scanned repo as untrusted input. It:
- **never** modifies your repos, apart from the opt-in hooks and Cursor's `--per-repo` rule (both
  marked blocks, removed cleanly);
- **never** opens `.env` files, private keys, or credential files, and never reads through a symlink
  or junction inside a repo;
- **never** runs code from a repo: its git calls turn off fsmonitor, hooks, and the repo's own
  filters.

It also:
- **redacts** common secret formats from every stored snippet, and stores git remotes without
  credentials;
- **keeps README text out** of always-loaded context. Repo names that do appear are flattened and
  capped, so they can't inject instructions or break cairn's blocks.

cairn makes **no network calls and collects no telemetry**. `cairn bench` is the only feature that
runs another program that does (the `claude` CLI).

See [SECURITY.md](https://github.com/Moe1177/cairn/blob/main/SECURITY.md) for the threat model and
how to report a vulnerability.

## Reference

### Commands

| Command | What it does |
|---|---|
| `cairn init` | Scan, then offer to add the index to Claude Code |
| `cairn scan [--full] [--verbose]` | Map every repo under the folder into `.cairn/` |
| `cairn refresh` | Re-read only repos whose HEAD or working tree changed |
| `cairn status` | What cairn knows, unconfirmed links, missing or stale summaries |
| `cairn annotate-edge KEY --confirm\|--reject [--why TEXT]` | Settle a relationship |
| `cairn set-summary REPO TEXT [--alias NAME]` | Save a summary (`-` reads stdin) |
| `cairn install <claude\|codex\|gemini\|cursor\|all>` | Load cairn into an agent harness |
| `cairn uninstall <name\|all>` | Remove it again |
| `cairn hooks install\|uninstall` | Opt-in git hooks that refresh after commits and merges |
| `cairn serve` | The MCP server (harnesses start it for you) |
| `cairn bench SUITE` | Run the benchmark harness |
| `cairn --version` | Versions of cairn, Python, the platform, and mcp |

**Exit codes:** `0` means success, `1` an error (one line on stderr), and `2` a usage error.

### What cairn writes, and where

| Path | What it is |
|---|---|
| `<folder>/.cairn/INDEX.md` | One line per repo: name, aliases, summary, stack |
| `<folder>/.cairn/cards/<repo>.md` | One card per repo |
| `<folder>/.cairn/workspace.json` | The full graph |
| `<folder>/.cairn/cache/`, `logs/`, `.lock` | Scan cache, last scan log, lock file |
| `<folder>/.cairn/relations.yaml`, `authored/` | **Yours:** aliases, manual links, summaries, decisions |
| `<folder>/CLAUDE.md` | A marked block holding the index (`cairn install claude`) |
| `~/.claude/skills/cairn/` and Claude's user MCP config | `/cairn` skill and MCP server |
| `~/.codex/AGENTS.md`, `config.toml`, `skills/cairn/` | Codex pointer, MCP server, skill |
| `~/.gemini/GEMINI.md`, `settings.json`, `commands/cairn.toml` | Gemini CLI pointer, MCP server, command |
| `~/.cursor/mcp.json`, `commands/cairn.md` | Cursor MCP server and command |
| `<repo>/.git/hooks/post-commit`, `post-merge` | Only with `cairn hooks install` |
| `~/.cairn/registry.json`, `backups/` | Mapped workspaces; one private backup of each config file cairn first edited |

cairn only edits its own key or marked block in other tools' files, and refuses to touch a file it
can't parse.

### Uninstall

```bash
cairn uninstall all          # harness entries, skills, commands, Cursor rules
cairn hooks uninstall        # if you installed hooks
uv tool uninstall cairnmap   # or: pipx uninstall cairnmap
```

Then delete `<folder>/.cairn/` and `~/.cairn/`.

### Troubleshooting

| Symptom | Fix |
|---|---|
| "No git repos found under …" | Run cairn from the folder that *contains* your repos |
| "… is inside the git repository …" | Same: run from the parent folder, not inside a repo |
| "git not found on PATH" warning | Install git; without it, remotes, HEAD and caching are off |
| "another cairn process is still updating this workspace" | A scan or hook refresh is running; retry in a moment |
| An agent says it can't find the workspace | Run `cairn init` in the workspace folder, then restart the agent session |
| `cairn install codex/gemini/cursor` refuses a config | That file isn't valid TOML/JSON; fix it and re-run (cairn never guesses) |
| Hooks did nothing | `cairn hooks install` lists the repos it skipped and why |

## Roadmap

1. ✅ Core map, precision pass, MCP server, harness integrations, freshness, benchmarks, release
   hardening (0.1).
2. ✅ HTTP, gRPC, pub/sub, compose and env-var relationships; packages inside monorepos (0.2).
3. Deep per-repo queries via [graphify](https://github.com/Graphify-Labs/graphify).
4. Efficiency: faster scans on very large workspaces, faster and more reliable CI, and product
   polish (`cairn doctor`, shell completion).
5. Larger benchmark suites (real open-source workspaces), significance testing, and more harnesses.

## Contributing

Issues and pull requests are welcome. See
[CONTRIBUTING.md](https://github.com/Moe1177/cairn/blob/main/CONTRIBUTING.md) for setup and checks,
and the [changelog](https://github.com/Moe1177/cairn/blob/main/CHANGELOG.md) for what's new. By
participating you agree to the
[code of conduct](https://github.com/Moe1177/cairn/blob/main/CODE_OF_CONDUCT.md).

## License

cairn is licensed under the **Apache License 2.0**: use it, modify it, and ship it, commercially
too. Keep the license and the [NOTICE](https://github.com/Moe1177/cairn/blob/main/NOTICE) file
with any redistribution. Full text: [LICENSE](https://github.com/Moe1177/cairn/blob/main/LICENSE).

Runtime dependencies and their licenses:

| Package | License |
|---|---|
| [typer](https://github.com/fastapi/typer) | MIT |
| [pydantic](https://github.com/pydantic/pydantic) | MIT |
| [PyYAML](https://github.com/yaml/pyyaml) | MIT |
| [pathspec](https://github.com/cpburnz/python-pathspec) | MPL-2.0 (used unmodified as a library) |
| [mcp](https://github.com/modelcontextprotocol/python-sdk) | MIT |
