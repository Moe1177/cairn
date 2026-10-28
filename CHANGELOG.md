# Changelog

All notable changes to cairn are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and cairn uses
[Semantic Versioning](https://semver.org/). Until 1.0, minor versions may change the map format;
`.cairn/authored/` and `.cairn/relations.yaml` (what you write) stay compatible.

## [Unreleased]

### Added
- **`links` and `related` reach org repos nobody cloned.** With `orgs:` in the config, after the
  map's own links comes a list of the org's uncloned repos linked to this one by packages: those
  defining a package it uses (`→`), and those using a package it defines (`←`, when its remote
  is the package's home). Read from the org's package cache, so it stays offline, and empty
  until `org_packages` has read the org. A widely used library shows ten, then a count.
  `cairn links --json` adds them under `org_links`; `--evidence` shows the manifest behind each.
- **Sessions that start in one repo: `cairn bench --scope repo`.** Each task's session runs with
  only its starting repo on disk and the suite's org (`org:` in `suite.yaml`) configured, its
  caches read once beforehand. Claude Code's file tools are confined to the session's workspace
  and denied the run's other folders and the suite. Answers are graded against the whole pinned
  workspace, with the org tools' `owner/repo/path` and links read as workspace paths. Before the
  sessions, the run checks each answer file and keyword on the org's default branch and notes
  in the log what moved since the suite's pinned commit. Results (11 hard tasks):
  [bench/published/2026-10-27-single-repo.md](bench/published/2026-10-27-single-repo.md).
- **`search_org`: where the org's code uses a name.** Which templates import an export, what
  reads a metric, env var or queue, which repo builds an image: the org's code search on GitHub
  or GitLab, worded as uses rather than prior art. `find_across` knows only the repos on disk,
  and now ends with a pointer to it when an org is configured. From one repo, it turned
  `retire-core-api-keys` from failed to answered for Haiku and Sonnet, in all three runs.
- **`read_org_file` finds its way in a repo nobody cloned.** A folder's path lists what the folder
  holds, and a path that isn't there lists the files it most likely meant: the same path in
  another case (`readConfig.go` -> `readconfig.go`), files of the same name anywhere, then paths
  spelled alike, or else what its nearest existing folder holds. From one repo, Sonnet answered
  23 of 33 hard-task runs instead of 16 with it.
- **Orgs on any git host.** An org in the config can list its repos by URL (`repos:`, https or
  ssh), and cairn reads them through git itself with git's own login: Gitea, Forgejo,
  Bitbucket, sourcehut or a bare server. It keeps one clone per repo holding only its latest
  list of files (`--filter=blob:none --depth=1`), and fetches the files it reads in one request
  per repo; `git ls-remote` tells which repos changed. On gitlab.gnome.org, GNOME's 317 repos
  took 37 s to index cold and 9 s warm, in a 15 MB cache; World/Rust gave the same shared
  packages as the GitLab API. `read_org_file`, `org_profile`, `org_packages`, `resolve_repo` and
  `repo_card` work there; `find_similar` says plain git has no code search.
- **GitLab orgs.** Every org feature (`find_similar`, `read_org_file`, `org_profile`,
  `org_packages`, and the catalog behind `resolve_repo` and `repo_card`) now reads GitLab too:
  gitlab.com or self-managed, and a group with its subgroups (`org: acme/platform`), with your
  `glab` login or `GITLAB_TOKEN`. A GitLab tree comes 100 entries a page, every folder before
  any file, so cairn reads the pages side by side (gimp-help's 6,959 files: 2.8 s). On
  gitlab.gnome.org, GNOME's 316-repo catalog took 10 requests (1.2 s), and the package index of
  World/Rust (33 repos, nested three groups deep) 182 requests (4.4 s). Code search across a
  group needs GitLab's advanced search; without it, `find_similar` says so.
- **Org repos nobody cloned, where agents already look.** With `orgs:` in the config,
  `resolve_repo` also answers from the org's repo catalog ("the terraform provider for AWS" ->
  `hashicorp/terraform-provider-aws`), and `repo_card` describes an uncloned org repo: its
  listing facts, the packages it defines, the org libraries it uses, and the workspace repos
  that depend on it. INDEX gains a short section (`org_index_repos`, 15 by default) of the org
  repos the workspace depends on, then the most used ones, written from the caches only and
  without any repo-written text. The catalog is the org's listing (604 repos: 2.5 s), cached for
  a day; a search takes about 1.4 ms. `cairn bench-repos` compares it with GitHub's repository
  search: held out on grafana, first-place hits 10 of 16 against 8 of 16 for GitHub given the
  query an agent types for an org it doesn't know.
- **The org's own packages: `org_packages` and `cairn org-packages`.** The libraries an org's
  repos use from one another, most shared first. Each comes with where it is defined (the repo
  and manifest, a monorepo's subfolder included) and which repos use it. Pass a name to see
  one package's users and up to five files that import it. Every active repo's tree and
  manifests are read over GitHub's API (hashicorp's 604 repos: 35 s), then cached. A refresh
  after a day reads only the repos pushed since (2.3 s when none were), and when the hour's
  API budget runs low, it leaves the rest for the next call. `cairn bench-packages` measures
  whether an agent names the org's library for a task. With the org's name masked, an agent
  alone named none for hashicorp; after reading the list, it named the right one for all 26 dev tasks
  and all 14 held-out grafana tasks.
- **The org's stack: `org_profile` and `cairn org-profile`.** A few lines that say what the org's
  200 most recently pushed repos build with: languages, datastores, queues, web frameworks,
  auth, test and deploy tools, the most used libraries per ecosystem, and the org's own packages
  that other repos depend on, each with the share of repos that use it. It reads each repo's
  file tree and up to three manifests over GitHub's API (about 15 s for 200 repos), then answers
  from a cache for a week. `cairn bench-prior-art` gains a `cairn-profile` locator,
  `--make-profile`, and a terms file per locator. Measured honestly: search terms written after
  reading the profile did not find more prior art (held-out hit@5 0.83 against 0.92 without it).
- **Prior art across your org, without cloning it.** Name an org in `.cairn/config.yaml`
  (`orgs: [{org: acme}]`, GitHub or GitHub Enterprise) and agents get two tools:
  `find_similar(task, terms)` finds where the org already implemented a feature, and
  `read_org_file(repo, path)` reads what it found. `cairn similar TASK --terms A,B` does the same
  from a terminal. The agent passes words the code would contain; each becomes a code search, all
  run at once, and hits are merged by rank with vendored copies, docs, configs and tests weighed
  down or dropped. Calls reach only the configured orgs. On `aws-samples` (~9,300 repos), the
  top five held an existing implementation for 17 of 18 tuning tasks and 10 of 12 held-out
  tasks (one plain search of three task words: 5 of 18, 2 of 12), in about 0.6 s a task.
- **`cairn bench-prior-art`**, an offline benchmark for orgs too big to clone. Given a feature to
  build ("stop one client from flooding our API"), does a locator find the org's existing
  implementation of it, and how fast? It runs over GitHub's API (github.com or Enterprise), with
  nothing cloned, and scores hit@k, MRR, recall, tokens and time per task, plus what share of each
  top five the key has judged. The first suite covers `aws-samples` (~9,300 repos) with 18 tasks:
  7 that name the technology and 11 that describe the need in words the code rarely uses. Tokens
  come from `GH_TOKEN`/`GITHUB_TOKEN` or `gh auth token`; rate limits are waited out.
- **Hard benchmark tasks.** 11 tasks on OpenFaaS and One Login whose answers no search for the
  prompt's own words finds, and whose prompts don't name the repo the answer is in. The agent has
  to read an identifier in code first (an image, a stack export, a Pact provider name, a NATS
  subject) and follow it to a repo it works out. `cairn bench-reach SUITE...` checks this offline
  for every task, and fails on a task marked `hard: true` that breaks either rule. In a first
  pilot, Sonnet answered all 11 with or without a map
  (`bench/published/2026-10-11-hard-tasks.md`).
- **`cairn bench-regrade SUITE LOG`** grades a finished run's log again with today's grading,
  against a fresh copy of the suite's repos.
- **Codex in the benchmark.** `cairn bench --harness codex` runs each task through `codex exec`
  (read-only sandbox, approvals off, sessions not saved) instead of Claude Code, with the same
  conditions and grading. Runs ignore your Codex config and rules and turn off connected apps,
  plugins, web search, browsers, hooks and sub-agents; the condition's context is given as
  developer instructions and its MCP server with `-c`. It refuses to start while your Codex
  home holds a global AGENTS.md, which Codex would load into every condition.
- **Draft summaries.** Until someone writes a repo's summary, INDEX, its card and
  `resolve_repo` show cairn's draft of what kind of repo it is, from what it detected:
  `draft: web app (104 routes, owns 46 tables)`, `draft: deploy config (deploys 7 repos)`,
  `draft: library (used as a package by 2 repos)`. Drafts are built from counts and cairn's own
  words only, never README, package or topic names, so INDEX still carries no repo-written text.
  A lone route or resource (often a test fixture's) doesn't count, and a repo cairn knows
  nothing about still reads "no summary yet". `/cairn` now checks the draft as it writes the
  summary.
- **Maven and Gradle.** A JVM library now links to the repos that build against it, the way an
  npm package does: cairn reads the `group:artifact` each `pom.xml` and `build.gradle(.kts)`
  publishes (wherever the module sits, with groups inherited from a parent pom or an
  `allprojects` block) and the coordinates each one depends on. Builds are read with patterns,
  never an XML parser or Gradle, so an untrusted pom can't expand entities and nothing runs.
- **A link benchmark on real repos.** `cairn bench-links SUITE...` scores the links cairn finds
  against a suite's `links.yaml`, the pairs of repos that really link, written from the code.
  It reports precision, recall and direction for the links cairn shows and, separately, for its
  unconfirmed suggestions, and lists every missed and wrong link. Offline and free. Keys for Sock
  Shop, Supabase JS (held out), fleetline and shopverse: cairn shows 46 of 48 real links and no
  wrong ones.
- **Two real-world suites, both held out.** OpenFaaS (`bench/suites/openfaas`): 38 repos, ten
  tasks whose answers sit in repos whose names don't hint at them, and 88 real links. GOV.UK One
  Login's identity-proving services (`bench/suites/onelogin`): 10 repos linked through AWS
  (SQS, DynamoDB, SSM, Lambda, exports), 24 real links. cairn finds 11 of One Login's 12 AWS
  links with none wrong; OpenFaaS shows where it falls short (README mentions of a CLI everyone
  installs, Go modules outside the repo root, Gradle builds).

### Changed
- `cairn bench` copies a suite into git repos once per benchmark, not once per run, and sets
  each condition up in place. A 38-repo suite took about 27 minutes to copy on Windows.

### Fixed
- **Benchmark grading credits a path its line gives a repo for.** "`openfaas/faas`:
  `gateway/metrics/metrics.go`" and "in the `faas-middleware` repo, at `oauth/config.go`" now
  count for the repo the line names nearest the path, when the starting repo has no such file
  and that repo has. Regrading the 2026-10-11
  hard-task logs changes one run, from failed to answered.
- **Benchmark grading credits two more ways of naming a file.** A path in a table row whose own
  cell names the repo (`| ipv-cri-kbv-api | infrastructure/lambda/template.yaml |`) now counts
  for that repo. A path written under a folder named once above it now counts for the one
  workspace file it is the end of. Three correct answers in the hard-task pilot had been graded
  as failures.
- A README that runs a sibling as a command (`faas-cli deploy`, `| faas-cli login`, a `` `faas-cli
  new` `` code span) linked the two repos: running a tool isn't depending on its repo. Those lines
  now only mark the sibling as a tool, and a plain mention of a tool is an unconfirmed suggestion
  unless the tool's docs name the repo back. On OpenFaaS this removed 15 of 19 wrong links.
- Go modules outside a repo's root (`gateway/go.mod`) were never read: every go.mod in a repo now
  is, except local ones (`module handler/function`), which no other repo can depend on.
- Benchmark grading missed a file named with a line number (`lib/cart.ts:7`, `#L12`), the way
  Codex links files.
- The locate and link benchmarks took the fetched tree's own `.complete` marker as theirs, so an
  interrupted copy looked finished and was used half-made.

## [0.8.2]

### Added
- **See which repos a repo links to.** `cairn links` (in a repo, or `cairn links <repo>`) and a
  new `links` MCP tool give the same answer, one line per linked repo with its direction:
  `→ one way` (this repo uses it), `← one way` (it uses this repo) or `↔ both ways`, then what
  connects them ("calls it (2 routes)", "uses this repo's SQS queue jobs", "shares 10 tables").
  Ask any agent "which repos does this repo link to?" and it answers with that list.
  `--evidence` adds the file:line behind each link, `--all` includes unconfirmed links, `--json`
  is for scripts. The Claude Code plugin adds `/cairn:links`.

### Fixed
- `cairn uninstall claude` said "cairn was not installed" when there was no CLAUDE.md block,
  even though it removed the skill and the MCP server. It now says what it removed.

## [0.8.1]

### Added
- **A Claude Code plugin.** `/plugin marketplace add Moe1177/cairn`, then
  `/plugin install cairn@cairn`, is the whole setup for Claude Code users (it needs uv). It
  starts the MCP server, adds the `/cairn` skill, and loads the index into each session through
  a session-start hook instead of a block in CLAUDE.md. In one repo of a folder of repos with no
  map, Claude offers to build one; the `/cairn` skill now knows how (confirm the folder, run
  `cairn init`).
- **Without uv, the plugin says so.** The first session shows a warning, and Claude offers once
  to install uv with its official installer, running it only if the user agrees (Claude Code
  asks before it runs). The plugin's scripts also find a uv that isn't on PATH where uv's
  installer or pip puts it (pip's per-user Scripts folder often isn't on PATH), including one
  installed during the session; the MCP server needs a restart of Claude Code.
- **`cairn context`** prints what a session should know about its folder: the index (cut at a
  whole line to fit Claude Code's hook limit, saying how many repos were left out), an offer to
  build a map, or nothing. It prints nothing when CLAUDE.md already loads the index.

### Changed
- The MCP server finds the workspace again on every call when it started outside one, so a map
  built during a session works without a restart.
- `cairn init` never prompts when no one can answer (an agent's shell, CI), and leaves Claude Code
  to the plugin when the plugin is on; `cairn install claude` does nothing then, and
  `cairn status` names the plugin as the Claude Code integration.
- `cairn` commands no longer import the MCP library unless they serve, so the session hook
  starts quickly.

## [0.8.0]

### Added
- **AWS resources link the repos that create them to the repos that use them.** cairn reads
  Terraform, CloudFormation/SAM, Serverless Framework and CDK, and records which repo creates
  each SQS queue, SNS topic, DynamoDB table, S3 bucket, EventBridge bus, Kinesis stream, SSM
  parameter and CloudFormation export. ARNs, queue URLs, `${ssm:}` and `${cf:}` lookups,
  `Fn::ImportValue`, Terraform `data` blocks, SAM policy templates, SDK calls and env vars such
  as `ORDERS_TABLE: orders-prod` then link the user to the creator (`uses_resource`). Names match
  across stages, so `orders-${sls:stage}` and `orders-prod` are one table. EventBridge sources
  link publishers (`PutEvents`) to subscribers (rule patterns) as pub/sub links.
- Stack labels `serverless`, `aws-sam`, `aws-cdk` and `terraform`.
- **Lambda functions** join the AWS resources: a function is created by Terraform
  (`aws_lambda_function`, the lambda module), CloudFormation/SAM (`FunctionName`), CDK
  (`functionName`) or serverless, whose functions are named `<service>-<stage>-<key>`. A repo
  that invokes it by name or ARN (IAM grants, `LambdaInvokePolicy`, SDK `invoke`, CDK
  `fromFunctionName`, env vars like `CHARGE_FUNCTION`) links to the repo that creates it.
- **SSM parameters that no IaC creates** (written by a deploy script, say) link to the repo their
  path names: `/amplify/${stage}/amplify-admin/TABLE` links to the repo whose serverless service,
  id or alias is exactly `amplify-admin`. Only an exact name counts, never a shared word, and
  never the app prefix (the path's first segment). Cards say "reads SSM parameter … (its path
  names this repo)".
- **Railway**: a call to `api.railway.internal` (Railway's private network, with or without
  `http://`) or a reference variable holding another service's address
  (`${{api.RAILWAY_PRIVATE_DOMAIN}}`, `${{api.URL}}`) links to the repo named `api`. Caddyfiles,
  `*.conf` files and env templates are read for these explicit forms only, so an upstream alias
  like `http://backend` never counts; nor do database plugins (`${{Postgres.DATABASE_URL}}`),
  shared variables, or GitHub Actions contexts (`${{ secrets.API_URL }}`). Stack label `railway`
  from `railway.json`/`railway.toml` or a CI workflow that runs `railway up`.
- **Fly.io**: the `app` in a repo's `fly.toml` becomes an alias of that repo, and a call to
  `<app>.internal` (also behind a region or `top2.nearest.of.`), `<app>.flycast` or
  `<app>.fly.dev` links to it. Cloud names that end in `.internal` but aren't apps
  (`metadata.google.internal`, `*.ec2.internal`, `host.docker.internal`) and code paths
  (`from google.protobuf.internal import`, `io.grpc.internal.Foo`) never count. Stack label
  `fly` from `fly.toml` or a CI workflow that runs `flyctl deploy`.
- **Render**: a Blueprint (`render.yaml`) deploys every service whose `repo:` names a sibling
  repo (`deploys`), and a `fromService` reference links the repo of the service that reads it to
  the repo of the service it reads: an address (`host`, `hostport`, `port`) is a call, a copied
  env var a use. Services a repo's own Blueprint defines become aliases of that repo (Render's
  private network reaches them by name). A service name two Blueprints define, a `repo:` outside
  the workspace, databases and env groups never link. Stack label `render`.

### Changed
- The scan cache format is version 7, so the first scan after upgrading re-reads every repo.
- Generated deploy output (`.terraform`, `cdk.out`, `.serverless`, `.aws-sam`) is never scanned.

### Fixed
- **MySQL tables quoted with backticks were misread or missed.** `CREATE TABLE IF NOT EXISTS
  `assets`` was read as a table named `if`, and `CREATE TABLE `assets`` found no table at all.
  Backtick and SQL Server bracket (`[dbo].[t]`) quoting now name the table. A column default
  `ON UPDATE CURRENT_TIMESTAMP` is no longer read as an UPDATE of a table called
  `current_timestamp`. Both had produced bogus shared-database links between MySQL services.

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
