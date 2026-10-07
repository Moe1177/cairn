# Changelog

All notable changes to cairn are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and cairn uses
[Semantic Versioning](https://semver.org/). Until 1.0, minor versions may change the map format;
`.cairn/authored/` and `.cairn/relations.yaml` (what you write) stay compatible.

## [Unreleased]

## [0.7.2]

### Fixed
- **Copies of one app were sometimes not linked after a full scan.** cairn finds copies through
  each repo's first commit. Listing it walks the repo's history, which took up to 3 s per repo
  on a real workspace. Under a full parallel scan it passed cairn's 5 s limit, and the copy
  links were dropped silently; the empty answer could even be cached. Now:
  - the lookup gets 30 s;
  - its answer is remembered until HEAD moves or the history is reshaped (a shallow clone
    deepened, a graft or replace ref), so an edit that isn't committed doesn't ask again;
  - a timeout warns ("links between copies of one app may be missing") instead of being read
    as "no copies", and is never cached.

### Changed
- The scan cache format is version 6, so the first scan after upgrading re-reads every repo.
  This clears any "no copies" answers a timed-out lookup may have cached.

## [0.7.1]

### Fixed
- **A deep index whose rebuild fails or times out is no longer retried on every refresh.** Before,
  each refresh retried it, for up to 15 minutes each time, including the refreshes that commits
  to *other* repos trigger.
  - The failure is recorded against the state the build started from.
  - `cairn refresh` retries only once that repo changes. A commit to the repo itself still
    triggers a retry.
  - `cairn deep build`, including `--stale`, always retries.
  - `cairn deep status` shows "last build failed".
- **Benchmarks recognise far more usage-limit wordings.** The pattern held two stray control
  characters, so only "hit your … limit" matched. Wordings like "usage limit reached", "rate
  limited", "5-hour limit" or a 429 `rate_limit_error` were logged as real failures: they didn't
  stop the run, and `--resume` didn't redo them.
- **`query` lists each place once across copies of one app.** Repos that share their first commit
  (a per-event copy of an admin panel, say) used to show every hit twice, once per copy, which
  wasted half the answer. Now the same file and line shows once, followed by
  "(same in admin-2026)": the copy has the same place, so check it there too. Only repos the
  map confirms as copies are merged, never on a shared package name alone. Plain-word searches
  no longer call `const applications = …` a "(definition)".
- **A benchmark run that ends without a result** (claude stopped right after starting) now counts
  as an error, not as a clean empty answer. Its text is claude's error output, never the tool
  output in the stream, so it can't be graded as an answer or mistaken for a usage limit.

### Changed
- **Benchmark runs record which tools the agent called** (`--output-format stream-json`). Run and
  combined reports gain a "Tools used" table: how many runs called cairn's MCP tools, and Grep
  and Read calls per run. Older run logs still load, without tool counts.

## [0.7.0]

### Added
- **`query` finds the place in any repo, no install needed.** It searches with grep first: the
  question's identifiers, routes and quoted messages, else its words, through cairn's hardened
  `git grep`, with lockfiles, minified and generated files skipped. For "who calls X" it lists the
  callers before the definition. It also searches repos the question names, and the repos the
  map relates to the one asked about unless an identifier, route or message already answered.
  Every answer says which search answered and why, and when a search stopped early at its time
  or size limit. Files cairn never opens (`.env`, keys, `secrets.yaml`…) are never searched. A deep index, when built, names the symbol on grep's hits and answers when
  grep finds nothing.
- **`cairn deep enable`** installs graphify as its own tool (uv, else pipx, else pip; it asks
  first) and indexes every repo. `cairn refresh` then keeps existing deep indexes fresh by default
  (`--no-deep` skips), and `cairn doctor` reports how many repos are indexed and which are stale.
- **`cairn bench-locate`**, an offline locate benchmark (no agent, no cost). It scores grep, the
  code graph and the hybrid on questions written from the code: 76 across sockshop, fleetline
  and shopverse (dev) and supabase-js and networkx 3.4.2 (held out).
  [Results](bench/published/2026-10-06-locate.md):
  - grep matched or beat the code graph on every kind of question;
  - searching the way `query` does, the grep-first hybrid raised held-out hit@1 from 0.42 to 0.50
    (MRR 0.52 to 0.57) at equal hit@5, almost all of it on "who calls X" questions;
  - questions worded differently from the code stay hard for both (hit@5 at most 0.38).

  A follow-up agent run (288 runs, Haiku and Sonnet, 16 localization and impact tasks) found
  **no measurable gain from `query`** over the INDEX and cards alone. Haiku even took about 2 more
  turns, though that isn't significant
  ([results](bench/published/2026-10-06-agent-query.md)).

### Changed
- Deep queries answer from memory. The MCP server keeps each parsed graph (LRU of 8), ranks only
  symbols that share a word with the question, and reuses a staleness verdict for 5 seconds. On
  an 11.7k-symbol graph a repeated graph lookup takes about 11 ms (was about 250 ms). A full
  `query`, now grep first, takes about 140 ms warm on networkx (Windows).
- The scan's per-line keyword gates are compiled regexes, with whole-file prechecks: 14% less
  scan CPU and byte-identical output. Wall time barely moves, because a Windows scan waits mostly
  on git process start-up.
- The README's privacy section names the commands that reach the network: `cairn deep enable`
  and the two benchmarks.

## [0.6.0]

### Added
- **Copies of one app.** Repos that share their first commit (a registration site cloned for each
  event, say) are linked as one family (`mirrors`): cards say "copy of the same app: change one,
  check the other" and INDEX lines list the copies. The same package name only suggests a copy
  (unconfirmed). Between copies, a shared schema, env names or copied docs are only suggestions
  (per-event copies often use a database each; a service split from a monolith may really share
  one, so confirm it with `annotate-edge`), and a relation you declare always stands. Only
  first-parent history counts, so a subtree merged in later isn't "a copy"; shallow clones don't
  find their family.
- **MongoDB.** Mongoose models and driver `.collection("x")` calls are database tables, so apps
  on the same collections link. Collections are named exactly as Mongoose does (its pluraliser,
  ported), or by the third argument or a lone schema's `collection` option; models split across
  lines count. Only files that import mongoose/mongodb do (Firestore looks alike).
- **Git trust.** When git refuses a repo owned by another user ("dubious ownership"), the scan
  says so with the `safe.directory` command instead of quietly losing its HEAD, remote and
  cache; `cairn doctor` lists every such repo.

### Changed
- The scan cache format is version 5, so the first scan after upgrading re-reads every repo.

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

### Benchmarks
- 840 runs on four workspaces (Sock Shop as the development set, Supabase JS held out), Haiku 4.5
  and Sonnet 5.5, with intervals and Holm-adjusted paired tests. Significant: Haiku used 19% fewer
  fresh tokens with the INDEX, and Sonnet's INDEX runs cost 12% less than with a hand-written
  doc. Other savings (up to -26% on Sock Shop) aren't significant after adjustment, success rates
  didn't change, and some workspaces regressed. The first run's claim that Haiku reaches 100%
  with the INDEX did not replicate and is corrected. See
  `bench/published/2026-10-06-real-world.md`.
- Benchmark logs carry a settings header per invocation; `--resume` refuses another model, run
  count or conditions, and re-runs only usage-limit failures. Fetched suites are copied as is
  (no `dot-` renames, nested repos and git metadata removed) under hardened git.

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
