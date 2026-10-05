# Changelog

All notable changes to cairn are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and cairn uses
[Semantic Versioning](https://semver.org/). Until 1.0, minor versions may change the map format;
`.cairn/authored/` and `.cairn/relations.yaml` (what you write) stay compatible.

## [Unreleased]

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
