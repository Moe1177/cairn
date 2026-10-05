# Changelog

All notable changes to cairn are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and cairn uses
[Semantic Versioning](https://semver.org/). Until 1.0, minor versions may change the map format;
`.cairn/authored/` and `.cairn/relations.yaml` (what you write) stay compatible.

## [Unreleased]

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
