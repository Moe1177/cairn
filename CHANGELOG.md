# Changelog

All notable changes to cairn are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and cairn uses
[Semantic Versioning](https://semver.org/). Until 1.0, minor versions may change the map format;
`.cairn/authored/` and `.cairn/relations.yaml` (what you write) stay compatible.

## [Unreleased]

## [0.5.0]

### Added
- **Service-name links.** Calls addressed to a sibling's service name, as Docker and
  Kubernetes DNS do (`http://catalogue`, `http://carts:8080/carts`, `*.svc.cluster.local`), and
  host literals (`Hostname("payment")`, `host = "orders"`) link the caller to that repo.
- **Deploy repos.** compose, Kubernetes and Helm files that run a sibling's image
  (`image: acme/catalogue:1.2`) make a `deploys` link.
- **RabbitMQ (Spring AMQP).** `convertAndSend` publishers link to `@RabbitListener`,
  `setQueueNames` and listener-container consumers of the same queue.
- **Real-world benchmarks.** Suites can pin real repos at exact commits (`sources:`); two new
  suites, Sock Shop (9 repos) and the Supabase JS client family (6 repos, held out). Reports add
  95% bootstrap intervals, paired Wilcoxon tests against the cold and hand-written-doc
  baselines, and break-even. `bench/combine_results.py` pools suites and models.
- `cairn bench` stops at a usage limit and `--resume <log>` continues without redoing runs.

### Changed
- On Sock Shop, cairn found none of the 16 real service links in 0.4 and finds all of them now.
  The `microshop` evaluation workspace keeps these link types exact (precision 1.0) against
  their look-alikes.
- The scan cache format is version 4, so the first scan after upgrading re-reads every repo.

## [0.4.0]

### Added
- **`cairn doctor`** checks Python, git, the map, write access, harnesses and graphify (plus
  stale deep indexes), says what to fix, and exits 1 on a failure.
- **Shell completion:** `cairn --install-completion`.
- **"used by" on INDEX lines:** each repo lists up to three repos that depend on, call, or
  reference it. The benchmarks showed weaker models often answer from INDEX alone.
- `bench/perf_scan.py` times a scan on a synthetic workspace.

### Changed
- **Much faster scans.** Each repo is walked once and each file read once (detectors used to
  walk six times and read files four times), repos' live detectors run in parallel, and cheap
  keyword checks skip lines no detector pattern can match. On 200 repos and 50,000 files
  (Windows): first scan 156 s -> 53 s, refresh 15 s -> 5.4 s.
- **A refresh asks git one question per unchanged repo** (was five): HEAD and the origin
  remote are remembered by the stamp of the `.git` files that decide them, in
  `.cairn/cache/git-memo.json` (never for worktrees, reftable repos, symbolic refs, or configs
  with includes or per-worktree config). `cairn scan --full` ignores it.
- A refresh notices new git-ignored config and compose files: cached file lists are checked
  against each folder's modification time.
- `refresh --deep` re-scans after building; `--quiet` really is quiet; `deep build --stale` says
  when nothing is stale; `deep status` also takes `-w`. A half-written deep index says
  "incomplete, rebuild" instead of "no index". Hubs only list symbols in the repo, and graphify
  is also found in the interpreter's and the user's scripts folders.

### Fixed
- The test suite could write a `cairn` entry into the developer's real `~/.cursor/mcp.json`.
  Every test now runs with throwaway harness homes.

### Security
- Remote URLs are normalised (credentials stripped) where they are read, so no cache can hold
  them. A repo's own git filters are always neutralised from its current config: the git memo
  never decides them, so a tampered memo can't switch that protection off.

### Project
- CI: pull requests run one job per OS and per Python version (main, nightly and manual runs
  keep the full matrix); every job has a timeout; tests run in parallel; jobs no runner picked
  up are re-run once. The test suite runs in about a minute.

## [0.3.0]

### Added
- **Deep queries.** `cairn deep build REPO…|--all|--stale` indexes repos with graphify
  (`pip install 'cairnmap[graphify]'`); `cairn deep status` and `cairn deep clear` manage them.
  The MCP `query` tool then answers with `symbol — file:line` hits and their neighbours, and says
  when an index is stale.
- Cards gain a **Deeper** section (symbols, build sha, stale flag, busiest symbols).
- `cairn refresh --deep` rebuilds only the deep indexes that went stale. `cairn status` lists them.

### Security
- graphify always runs code-only (no LLM, no network) as a subprocess with an allowlisted
  environment, and writes only under `.cairn/deep/`. Graph files are size-capped and every label
  is sanitised before an agent sees it.

## [0.2.0]

### Added
- **HTTP links.** Routes from Next.js (file routes), Express, Fastify, Hono, FastAPI (including an
  `APIRouter` prefix), Flask, Go net/http, chi, gin, echo, and OpenAPI files are matched with
  client calls (`fetch`, `axios`, `ky`, `got`, `requests`, `httpx`, Go `http`). A link is `extracted`
  when the call's base URL env var or service host names the target.
- **gRPC links.** Server implementations (Go, Python, TypeScript, Java) are matched with client
  stubs.
- **Pub/sub links.** Kafka, NATS, and Redis publishers are matched with subscribers on specific
  topic names.
- **Compose links.** A `depends_on` between services built from (or named after) your repos.
- **Monorepo packages.** npm/yarn/pnpm, Cargo, `go.work`, and uv workspace packages are listed on
  the card. They publish and depend like repos, and the MCP tools resolve them by name.
- **Shared env vars.** These only corroborate other links; they are never shown on their own.
- **`servicemesh` evaluation.** A new evaluation workspace with look-alikes. Every new link type
  must be exact: precision and tier accuracy 1.0.

### Changed
- The scan cache format is version 3, so the first scan after upgrading re-reads every repo.
- A single file can produce at most 2,000 table facts.
- Generated gRPC stubs, generic services (Health, Query), WebSocket and HTTP-response `.send()`
  calls, public Docker images, and remote build contexts never create links.
- Internal workspace packages (`@repo/ui` in two Turborepos) never link unrelated monorepos.
- Compose and workspace YAML files are depth-checked before parsing, so a hostile file can't crash
  a scan.

### Upgrading
- Re-run `cairn install <harness>` after upgrading. The map gained fields that cairn 0.1 can't read,
  so a harness still pinned to 0.1 (an old `uvx` entry) would fail to load it.

### Known limitations
- Router prefixes mounted in another file aren't applied yet: FastAPI `include_router(prefix=...)`,
  Express `app.use('/api', router)`, and Flask blueprint `url_prefix`. Calls to those routes may not
  link. Precision is unaffected.

## [0.1.0]

First public release.

### Added
- **The map.** `cairn scan` maps every git repo under a folder into `.cairn/`:
  - `INDEX.md` lists every repo in about 30 tokens per repo and is always loaded;
  - each repo gets a card under `cards/<repo>.md`, read on demand;
  - `workspace.json` holds the full graph.
- **Relationships.** cairn finds links from shared packages, shared database tables, `../` path
  references, and documentation mentions. Each link is tagged `extracted`, `inferred`, or
  `ambiguous`.
- **Settling links.** `cairn status` lists unconfirmed links. `cairn annotate-edge` confirms or
  rejects them, and `cairn set-summary` saves a summary for a repo; both decisions survive
  re-scans.
- **Agent integrations.** `cairn install claude|codex|gemini|cursor|all` sets up each harness: the
  index, a `/cairn` skill or command, and the cairn MCP server.
  - The MCP server's tools are `resolve_repo`, `repo_card`, `related`, `find_across`, `query`, and
    `refresh`.
- **Freshness.**
  - `cairn refresh` re-reads only the repos that changed.
  - `cairn scan --full` re-reads everything.
  - Opt-in git hooks (`cairn hooks install`) refresh the map after commits and merges.
  - Summaries that may be stale are flagged.
- **Benchmarks.** `cairn bench` runs headless Claude Code under five conditions, from no map to the
  map plus MCP, and grades the answers deterministically. It ships with two suites:
  - `shopverse` (6 repos);
  - `fleetline` (15 repos).
- `cairn --version` prints the cairn, Python, platform, and mcp versions.

### Security
- Text from scanned repos is treated as data:
  - README text stays out of always-loaded context;
  - folder and package names are flattened, capped, and stripped of markers, so they can't break
    cairn's marked blocks.
- cairn never reads through symlinks or junctions inside a repo, never opens `.env` files or
  credential files, and redacts common secret formats from every snippet it stores.
- Git calls disable `core.fsmonitor`, hooks, and the repo's own filters, and take no optional
  locks.
- A map committed inside a repo is never served.
