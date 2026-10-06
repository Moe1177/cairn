# cairn

[![CI](https://github.com/Moe1177/cairn/actions/workflows/ci.yml/badge.svg?branch=main&event=push)](https://github.com/Moe1177/cairn/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/cairnmap?label=pypi)](https://pypi.org/project/cairnmap/)
[![Python](https://img.shields.io/pypi/pyversions/cairnmap?label=python)](https://pypi.org/project/cairnmap/)
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
- trips-svc: FastAPI service owning the trip lifecycle and the trips/trip_events tables · fastapi · used by admin-console
- ui-kit (@fleetline/ui-kit): Shared React components (Button, Card) · react · used by admin-console
```

`used by` lists the repos that depend on, call, or reference that one, so a change's blast
radius is visible before any card is opened.

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
| `query` | Where inside a repo: `symbol — file:line` from a deep index, else which folders to start in |
| `refresh` | Update the map now |

### What cairn detects

| Signal | Examples |
|---|---|
| HTTP calls | Next.js routes, Express/Fastify/Hono, FastAPI/Flask, Go (net/http, chi, gin, echo) and OpenAPI routes, matched with `fetch`/`axios`, `requests`/`httpx`, and Go `http` client calls |
| gRPC | Go, Python, TypeScript and Java servers matched with their client stubs |
| Service names | Calls addressed to a sibling's service name, as Docker and Kubernetes DNS do: `http://catalogue`, `http://carts:8080/carts`, `*.svc.cluster.local`, `Hostname("payment")` |
| Pub/sub topics | Kafka, NATS, Redis and RabbitMQ (Spring AMQP) publishers matched with subscribers (`trip.completed`) |
| docker-compose | `depends_on` between services built from (or named after) your repos |
| Deploy repos | compose, Kubernetes and Helm files that run your repos' images (`image: acme/catalogue:1.2`) |
| Package dependencies | npm (`workspace:*`, scoped packages), PyPI, Go modules, Cargo |
| Packages inside monorepos | npm/yarn/pnpm, Cargo, `go.work` and uv workspaces, listed on the card and resolvable by name |
| Shared database tables | SQL migrations and queries, Prisma, Drizzle, Supabase, MongoDB (Mongoose models, `db.collection("x")`) |
| Copies of one app | Repos that share their first commit (an app cloned per event or per client): "change one, check the other". The same package name only suggests it |
| Path references | `../trips-svc` in docker-compose, tsconfig, and other config files |
| Documentation | READMEs and docs that mention a sibling repo |
| Shared env vars | Specific names read by both sides. These only back up another link; they never make one on their own |

Look-alikes are deliberately ignored:
- health-check routes;
- calls to other companies' APIs;
- vague topic names;
- `.proto` files with no implementer;
- generic env vars such as `PORT`;
- `localhost`, public domains, and URLs in comments;
- public images (`mongo:3.4`) and look-alike names (`catalogue-db` is not `catalogue`);
- a queue that a repo declares but never consumes;
- the same schema in two copies of one app (copies often use a database each, so no link);
- Firestore's `db.collection(...)`, which looks like MongoDB's.

Evaluation workspaces in the test suite keep every one of these at precision 1.0.

## Deep queries

The map tells an agent *which* repo to open. A deep index tells it *where inside*: the `query` MCP
tool answers "where is login handled?" with `login() — src/auth.py:12` hits and their neighbours,
instead of a list of folders.

Deep indexes are optional and built per repo with [graphify](https://github.com/Graphify-Labs/graphify):

```bash
cairn deep enable                      # installs graphify if needed (asks first), indexes every repo
cairn deep status                      # size, build sha, fresh or stale
cairn refresh                          # also rebuilds stale deep indexes once any exist (--no-deep skips)
cairn deep build trips-svc             # one repo by hand; cairn deep clear trips-svc deletes it
```

`cairn deep enable` installs graphify as its own tool (`uv tool install graphifyy`, else pipx, else
pip), so cairn's own environment is left alone; `cairn doctor` shows how many repos are indexed.
You can also install cairn with the extra (`pip install 'cairnmap[graphify]'`); `cairn refresh --deep`
forces a deep rebuild check even before any index exists.

- graphify always runs `--code-only`: no LLM, no network, and an allowlisted environment, so no
  API key reaches it. It writes only to `.cairn/deep/<repo>/`, never into the repo.
- cairn answers queries itself from the saved graph, offline, so serving needs no graphify.
- The first build is something you ask for (`cairn deep enable` or `cairn deep build`): a large
  repo can take minutes. After that, `cairn refresh` (and the git hooks' background refresh)
  keeps indexes current, one build per repo at a time. When an index still falls behind, `query`
  and `cairn deep status` say so; the card's **Deeper** section flags new commits.

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

**Results** (2026-10-06): 840 runs over four workspaces, two of them real open-source systems:
Sock Shop (9 microservice repos; cairn's newest link types were developed on it) and the
Supabase JS client family (6 repos, held out: never used to tune cairn). 28 tasks, 3 runs per
cell, Haiku 4.5 and Sonnet 5.5. A result is called significant only after Holm adjustment.

| Per task, cairn INDEX (C) | Haiku 4.5 | Sonnet 5.5 |
|---|---|---|
| Fresh tokens vs no map | **-19%** (significant) | -10% (n.s.) |
| Cost vs no map | -25% (n.s. after adjustment) | -12% (n.s.) |
| Cost vs a hand-written doc | -6% (n.s.) | **-12%** (significant) |
| Cost vs no map, Sock Shop only | -27% (n.s.) | -26% (borderline, adjusted p = 0.055) |

What this shows:
- **cairn tends to make cross-repo work cheaper**: fewer fresh tokens for Haiku, and cheaper than
  a hand-written related-repos doc for Sonnet. The largest raw savings were on Sock Shop.
- **It doesn't measurably raise success.** Sonnet answers 99-100% of these tasks in every
  condition; Haiku rises from 86% to 93% with the MCP server, which isn't significant.
- **It isn't a win everywhere.** On fleetline, Sonnet cost 7-10% more with cairn than without
  (n.s.); the held-out Supabase effects are small and not significant.
- **Correction:** our first, smaller run (2026-10-05) reported Haiku reaching 100% with the
  INDEX. With more runs that doesn't replicate (89-92%, the same as no map).

Methods, every table with 95% intervals, paired Wilcoxon tests (raw and Holm-adjusted), the
regressions, and the held-out results:
[bench/published/2026-10-06-real-world.md](https://github.com/Moe1177/cairn/blob/main/bench/published/2026-10-06-real-world.md).
The first run is kept at
[2026-10-05-shopverse-fleetline.md](https://github.com/Moe1177/cairn/blob/main/bench/published/2026-10-05-shopverse-fleetline.md).

Run the benchmarks yourself from a source checkout. They use your Claude usage.

```bash
cairn bench bench/suites/sockshop --runs 3 --model haiku    # fetches the pinned repos once
cairn bench bench/suites/shopverse --conditions A,C --tasks gift-message
cairn bench bench/suites/sockshop --resume bench/results/<stamp>.jsonl   # after a usage limit
```

## Performance

cairn walks each repo once, reads each file once, and scans repos in parallel. A refresh
re-reads only repos whose HEAD or working tree changed, and asks git one question per
unchanged repo. On a synthetic workspace of 200 repos and 50,000 files (Windows 11, 12 cores):

| | 0.3 | 0.4 |
|---|---|---|
| First scan | 156 s | 53 s |
| Refresh, nothing changed | 15 s | 5.4 s |

Most of a refresh on Windows is git process start-up; Linux and macOS start processes faster.
Reproduce with `uv run python bench/perf_scan.py --out <dir>`.

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
| `cairn refresh [--no-deep]` | Re-read only repos whose HEAD or working tree changed, and rebuild stale deep indexes |
| `cairn deep enable` / `cairn deep build REPO…\|--all\|--stale [-w PATH]` | Build graphify code indexes so `query` answers with file:line (optional extra) |
| `cairn deep status` / `cairn deep clear [REPO…]` | List deep indexes (fresh or stale) / delete them |
| `cairn status` | What cairn knows, unconfirmed links, missing or stale summaries |
| `cairn annotate-edge KEY --confirm\|--reject [--why TEXT]` | Settle a relationship |
| `cairn set-summary REPO TEXT [--alias NAME]` | Save a summary (`-` reads stdin) |
| `cairn install <claude\|codex\|gemini\|cursor\|all>` | Load cairn into an agent harness |
| `cairn uninstall <name\|all>` | Remove it again |
| `cairn hooks install\|uninstall` | Opt-in git hooks that refresh after commits and merges |
| `cairn serve` | The MCP server (harnesses start it for you) |
| `cairn bench SUITE` | Run the benchmark harness |
| `cairn doctor` | Check git, Python, the map, write access, harnesses and graphify; exits 1 on a failure |
| `cairn --install-completion` | Tab completion for your shell (bash, zsh, fish, PowerShell) |
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
| Something seems off | Run `cairn doctor`: it checks each dependency and says what to fix |
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
3. ✅ Deep per-repo queries via [graphify](https://github.com/Graphify-Labs/graphify) (0.3).
4. ✅ Efficiency: 3x faster scans, faster and more reliable CI, `cairn doctor`, shell completion,
   and "used by" on INDEX lines (0.4).
5. ✅ Real-world reach (service DNS, deploy repos, RabbitMQ) and benchmarks on real open-source
   workspaces with significance testing (0.5).
6. More harnesses in the benchmark (Codex), and more ecosystems.

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
