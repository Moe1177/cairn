# cairn

[![CI](https://github.com/Moe1177/cairn/actions/workflows/ci.yml/badge.svg?branch=main&event=push)](https://github.com/Moe1177/cairn/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/cairnmap?label=pypi)](https://pypi.org/project/cairnmap/)
[![Python](https://img.shields.io/pypi/pyversions/cairnmap?label=python)](https://pypi.org/project/cairnmap/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/Moe1177/cairn/blob/main/LICENSE)
[![M8ven Score](https://m8ven.ai/badge/mcp/moe1177-cairn-uucfbk?v=cb2c7116a74e02b58201074faaf318da)](https://m8ven.ai/mcp/moe1177-cairn-uucfbk?s=readme)

**A map of all your repos for coding agents.** cairn scans every git repo in a folder once, works
out how they connect, and gives your agent:
- a tiny always-loaded index;
- a short card per repo.

The agent knows where things live without re-exploring.

> Cairns are the stacked-stone markers that guide hikers along a trail. cairn leaves small, cheap
> markers that guide coding agents to the right repo, and then to the right file.

Works with **Claude Code, Codex, Gemini CLI, and Cursor**, on **Windows, macOS, and Linux**.
Using Claude Code? [Install cairn as a plugin](#as-a-claude-code-plugin), or paste that section
into Claude Code and it installs everything for you.

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

### As a Claude Code plugin

If you use Claude Code, the plugin is the whole setup: it builds the map when you ask, loads it
into every session, and starts cairn's MCP tools. It runs cairn from PyPI through
[uv](https://docs.astral.sh/uv/).

**Type it yourself** in Claude Code, then restart Claude Code:

```
/plugin marketplace add Moe1177/cairn
/plugin install cairn@cairn
```

**Or ask Claude Code to do it.** Paste this section, or the link to it, into Claude Code and say
"install this". The steps below are written so Claude Code can follow them.

1. Check that uv is installed: `uvx --version`. If it isn't found:
   - uv may be installed but not on PATH (`pip install --user uv` puts it in
     `%APPDATA%\Python\Python3*\Scripts` on Windows, `~/Library/Python/3.*/bin` on macOS). If it's
     there, tell the user to add that folder to PATH instead of installing uv again.
   - Otherwise, ask the user before installing uv with its official installer:
     - macOS and Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
     - Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
2. Add the marketplace and install the plugin:
   ```
   claude plugin marketplace add Moe1177/cairn
   claude plugin install cairn@cairn
   ```
3. Check it: `claude plugin list` shows `cairn@cairn` as enabled.
4. If `~/.claude/skills/cairn/SKILL.md` exists, cairn was also installed with
   `cairn install claude`. Run `cairn uninstall claude`, or every cairn tool appears twice.
5. Tell the user to restart Claude Code, then open it inside any repo of their folder of repos.
   If that folder has no map yet, Claude offers to build one (or say "build the cairn map").

After that, every session starts with the map, and the cairn MCP tools are ready. The plugin never
edits `CLAUDE.md`. If uv goes missing later, the first session says so and Claude offers to install
it, only if you agree.

| To | Run |
|---|---|
| Update | `claude plugin marketplace update cairn`, then `claude plugin update cairn@cairn` |
| Remove | `claude plugin uninstall cairn@cairn` |

Codex, Gemini CLI and Cursor use `cairn install` instead (see Quick start).

## Quick start

```bash
cd ~/code              # the folder that CONTAINS your repos
cairn init             # scan, then add the index to ./CLAUDE.md (asks first)
cairn install all      # optional: Codex, Gemini CLI, Cursor, the /cairn skill, the MCP server
```

Open your agent in any repo under that folder. It now knows about every sibling repo.

To give each repo a good one-line summary, run `/cairn` inside your agent. It writes the summaries
with `cairn set-summary` and settles uncertain links. Until then, the index shows cairn's draft
from what it detected, such as `draft: web app (104 routes, owns 46 tables)` or `draft: library
(used as a package by 3 repos)`, and "no summary yet" where it found nothing to go on. A draft
is built from counts only: README text is deliberately kept out of always-loaded context.

## How to use it

### See what a repo links to

Inside any repo, run `cairn links`, or ask your agent "which repos does this repo link to?". Both
give the same answer:

```
trips-svc is linked to 3 repos:
  admin-console  ↔ both ways  shares 2 tables, mentions each other in docs
  payments-svc   ← one way    calls this repo (2 routes)
  rider-web      ← one way    calls this repo (3 routes)
```

`→ one way` means this repo uses the other one, `← one way` that the other one uses this repo,
and `↔ both ways` that each uses the other or they share something, like a database. Add
`--evidence` for the file and line behind each link. In Claude Code, the plugin's `/cairn:links`
does the same.

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
| `resolve_repo` | "Which repo is 'the payments service'?" With `orgs:`, the org's uncloned repos too |
| `repo_card` | The card for a repo (re-scanned first if its HEAD moved), or for an org repo nobody cloned |
| `links` | Which repos a repo is linked to, one line each with its direction (→ one way, ← one way, ↔ both ways); empty means the repo the session is in |
| `related` | Everything connected to a repo, with evidence |
| `find_across` | Which repos expose or use a table, package, or path |
| `query` | Where inside a repo: `file:line` hits, grep first, plus a deep index's symbols when built; says which search answered |
| `find_similar` | Where the org already implemented a feature (its repos on GitHub or GitLab, nothing cloned); needs `orgs:` in the config |
| `read_org_file` | A file from an org repo, without cloning it |
| `org_profile` | The org's stack: the datastores, frameworks, auth, test and deploy tools and libraries its active repos use, and its own shared packages |
| `org_packages` | The org's own libraries its repos share, where each is defined and who uses it; with a name, one package's users and code that calls it |
| `refresh` | Update the map now |

### What cairn detects

| Signal | Examples |
|---|---|
| HTTP calls | Next.js routes, Express/Fastify/Hono, FastAPI/Flask, Go (net/http, chi, gin, echo) and OpenAPI routes, matched with `fetch`/`axios`, `requests`/`httpx`, and Go `http` client calls |
| gRPC | Go, Python, TypeScript and Java servers matched with their client stubs |
| Service names | Calls addressed to a sibling's service name, as Docker and Kubernetes DNS do: `http://catalogue`, `http://carts:8080/carts`, `*.svc.cluster.local`, `Hostname("payment")`; Railway's private network (`api.railway.internal`, also in Caddyfiles, `*.conf` and env templates) and its reference variables for another service's address (`${{api.RAILWAY_PRIVATE_DOMAIN}}`); Fly.io apps by their `fly.toml` app name (`orders.internal`, `iad.orders.internal`, `orders.flycast`, `orders.fly.dev`) |
| Pub/sub topics | Kafka, NATS, Redis and RabbitMQ (Spring AMQP) publishers matched with subscribers (`trip.completed`) |
| docker-compose | `depends_on` between services built from (or named after) your repos |
| Deploy repos | compose, Kubernetes and Helm files that run your repos' images (`image: acme/catalogue:1.2`); Render Blueprints (`render.yaml`) whose services deploy from a sibling repo (`repo: https://github.com/acme/orders`) |
| Render services | `fromService` references in a Blueprint link the repo of the service that reads another's address (`property: hostport`) or env var to the repo of the service it reads, wherever the Blueprint sits |
| Package dependencies | npm (`workspace:*`, scoped packages), PyPI, Go modules, Cargo, Maven and Gradle (`group:artifact`, in any module folder) |
| Packages inside monorepos | npm/yarn/pnpm, Cargo, `go.work` and uv workspaces, listed on the card and resolvable by name |
| Shared database tables | SQL migrations and queries, Prisma, Drizzle, Supabase, MongoDB (Mongoose models, `db.collection("x")`) |
| Copies of one app | Repos that share their first commit (an app cloned per event or per client): "change one, check the other". The same package name only suggests it |
| Path references | `../trips-svc` in docker-compose, tsconfig, and other config files |
| Documentation | READMEs and docs that mention a sibling repo |
| AWS resources | Which repo creates each SQS queue, SNS topic, DynamoDB table, S3 bucket, EventBridge bus, Kinesis stream, Lambda function, SSM parameter and CloudFormation export (Terraform, CloudFormation/SAM, Serverless Framework, CDK), and which repos use it: ARNs, queue URLs, `${ssm:}`/`${cf:}` lookups (an SSM parameter nothing creates links to the repo its path names exactly), `Fn::ImportValue`, Terraform `data` blocks, SAM policy templates, SDK calls, env vars like `ORDERS_TABLE`. EventBridge `PutEvents` sources are matched with rule patterns |
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
- Firestore's `db.collection(...)`, which looks like MongoDB's;
- the Terraform state bucket every repo's backend names, IAM wildcards (`arn:aws:sqs:*:*:*`),
  AWS's own event sources (`aws.ec2`), and generated deploy output (`cdk.out`, `.serverless`).

Evaluation workspaces in the test suite keep every one of these at precision 1.0.

### Why not read AWS resource tags?

Tags record who owns a resource in an AWS account. cairn answers a different question, which code
depends on which code, and it gets that from the repos alone:

- **Tags only describe the creator.** Half of every link is who *uses* a resource, and the repos
  that read a queue or a table don't tag it. Those links come from ARNs, SSM paths, exports and
  SDK calls in the users' code.
- **cairn reads code, not the account.** It makes no network calls and needs no credentials. The
  only tags it could see are in the IaC block that creates the resource, and that block already
  tells cairn which repo creates it. A tag only adds something when a central infrastructure repo
  creates resources for app repos; there, each user already links to that infra repo.
- **No tag key means "owning repo".** `team`, `app`, `service` and `Name` mean different things in
  different places, and tags drift from the code without anything noticing. A link from code
  evidence says which file and line it came from.

`cairn bench-links` scores links against real workspaces (One Login's AWS repos among them), so a
new signal like tags can be measured before it's trusted.

## Finding the place in a repo

The map tells an agent *which* repo to open; the `query` MCP tool tells it *where inside*. Ask
"where is login handled?" and it answers with `src/auth.py:12 login() — grep: login (definition)`.
How it searches:
- It runs grep first, through cairn's hardened `git grep`. It looks for the question's
  identifiers, routes and quoted messages, and failing those, its words.
- For "who calls X", it lists the callers before the definition.
- It also searches repos the question names, and the repos the map relates to the one asked
  about, unless an identifier, route or message already answered.
- It never searches files cairn never opens (`.env`, keys, `secrets.yaml`…).
- Every answer says which search answered and why. It needs nothing installed.

Deep indexes are optional, and built per repo with
[graphify](https://github.com/Graphify-Labs/graphify). A code graph names the symbol on grep's hits
and answers when grep finds nothing. cairn asks grep first because, on its offline locate
benchmark, grep matched or beat the code graph on every kind of question
([results](https://github.com/Moe1177/cairn/blob/main/bench/published/2026-10-06-locate.md)).

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

## Prior art across your org

Before an agent builds a feature, it should know whether the org already built it somewhere: the
team's rate limiter, its way of verifying webhooks, the retry helper everyone uses. In an org of
thousands of repos nobody has them all cloned, so cairn asks the code host instead. Nothing is
cloned or downloaded beyond the files an agent chooses to read.

Name the org in `.cairn/config.yaml`:

```yaml
orgs:
  - org: acme              # github.com; for GitHub Enterprise add `host: git.acme.com`
  - org: acme/platform     # a GitLab group (its subgroups too)
    host: gitlab.com       # self-managed: your host, plus `kind: gitlab` unless it starts with gitlab.
```

cairn uses your own login, so it sees exactly the repos you can: on GitHub `gh auth login` (or
`GH_TOKEN`), on GitLab `glab auth login` (or `GITLAB_TOKEN`, a token with `read_api`). Every org
feature works on both. On GitLab a repo's name is its full path (`acme/platform/api`), and
`find_similar` needs the group's code search, which is GitLab's advanced search (a paid tier on
gitlab.com, Elasticsearch or Zoekt when self-managed); without it, it says so. Then an agent calls `find_similar` with the feature and a few words its code would contain,
and `read_org_file` to read what it finds:

```text
find_similar(task="stop one client from flooding our API",
             terms=["RateLimiter", "X-RateLimit-Remaining", "express-rate-limit"])
Prior art in acme for `RateLimiter`, `X-RateLimit-Remaining`, `express-rate-limit`: 10 files (3 searches, 0.6s).
- gateway/src/middleware/rate-limit.ts  (matched RateLimiter, X-RateLimit-Remaining)
- ...
```

From a terminal: `cairn similar "stop one client from flooding our API" --terms
RateLimiter,X-RateLimit-Remaining`.

The words matter. A request rarely shares words with the code that answers it ("flooding" never
appears in a rate limiter), so the agent, which understands the request, supplies the code's
words. Each term is one code search; they run at once. Hits are merged by rank, so a file several
searches find rises, and what isn't prior art sinks or goes: vendored copies of libraries
(`node_modules`, `site-packages`, Lambda layers), docs, notebooks, configs, tests. On ~9,300
repos (`aws-samples`), a file that already implements the task was in the top five for 17 tasks
in 18 on the tasks cairn was tuned on and 10 in 12 on tasks written after it, against 5 in 18 and
2 in 12 for one plain search of three of the task's words, in about 0.6 s a task
([results](bench/published/2026-10-17-find-similar.md)).

Code search allows 10 requests a minute, so `find_similar` makes at most four (one per term);
past the limit it waits, and its answer says how long.

### The org's stack

New code should be built with what the org builds with. `org_profile` (or `cairn org-profile`)
says what that is, read from its 200 most recently pushed repos: their languages, datastores,
queues, web frameworks, auth, test and deploy tools, their most used libraries per ecosystem, and
the org's own packages that other repos depend on, each with the share of repos that use it:

```text
The stack of aws-samples (github.com): what its 200 most recently pushed repos use (share of those repos), read 2026-10-17.
Languages: Python 40%, TypeScript 26%, JavaScript 8%, ...
Datastores: S3 42%, DynamoDB 27%, OpenSearch/Elasticsearch 10%, PostgreSQL 8%, MySQL 7%, Redis 6%, ...
Auth: Cognito 26%, JWT 14%
Deploy and CI: Docker 54%, AWS CDK 50%, GitHub Actions 43%, Terraform 19%, ...
Python libraries: boto3 42%, strands-agents 24%, pytest 18%, requests 18%, ...
```

It reads one listing page per 100 repos, each repo's file tree and up to three of its manifests
(about 15 s, some 800 API requests), then answers from a cache for a week.

It does not make `find_similar` find more. Terms written after reading the profile found prior
art for 10 of 12 held-out tasks against 11 of 12 for terms written from the task alone
([results](bench/published/2026-10-17-org-profile.md)), so cairn doesn't tell agents to search
with it.

### The org's own packages

An agent adding logging, retries or a service client should reach for the org's own library,
not a public one, and call it the way sibling repos do. `org_packages` (or `cairn org-packages`)
lists the libraries the org's repos use from one another, most shared first, with where each
is defined:

```text
The own packages of hashicorp (github.com): the 226 libraries its 604 active repos use from one another, most used first (by how many repos), read 2026-10-17. ...
- github.com/hashicorp/go-hclog (Go) · 89 repos · in hashicorp/go-hclog — A common logging package for HashiCorp tools
- github.com/hashicorp/vault/api (Go) · 43 repos · in hashicorp/vault/api
- github.com/hashicorp/go-retryablehttp (Go) · 16 repos · in hashicorp/go-retryablehttp — Retryable HTTP client in Go
```

`query` narrows the list ("retry http"); a `name` shows one package: its manifest, every repo
that uses it (and which of a monorepo's projects), and up to five files that import it, found
with one code search. A package counts as the org's when one active repo defines it and another
uses it, or its name is under the org (`@acme/...`, `github.com/acme/...`); a fork is its home
only under the org's name, and a name several repos define is a template's, not a library.

It reads every active repo's file tree and manifests (hashicorp's 604 repos: 35 s, about 1,300
API requests), then answers from a cache. After a day it reads again, but only the repos pushed
since (2.3 s when none were). When the hour's API budget runs low, it stops with 500 requests to
spare and the next call reads the rest, most recently pushed first.

Told what to build, an agent that read the list named the right library for every hashicorp
task, and for all 14 held-out grafana tasks. With the org's name masked (a private org's
packages, which no model has read about), the agent alone named none
([results](bench/published/2026-10-17-org-packages.md)).

### Org repos nobody cloned

A session sees the repos on disk. With `orgs:` in the config, it sees the org's other repos too:

- `resolve_repo` also answers from the org's catalog: "the terraform provider for AWS" →
  `hashicorp/terraform-provider-aws (org hashicorp, not cloned)`. A repo here by that exact
  name wins, and a cloned org repo is listed once, as the local one.
- `repo_card hashicorp/go-hclog` describes an org repo nobody cloned: its description,
  language, topics and last push, the packages it defines and how many org repos use them, the
  org's libraries it uses, and which workspace repos depend on it.
- INDEX gains a short section: the uncloned org repos whose packages the workspace depends on,
  then those whose packages most org repos use (`org_index_repos`, 15 by default):

```text
## Org repos, not cloned (repo_card <owner/name> describes one; read_org_file reads it)
- hashicorp/go-hclog · Go · used here by my-svc · its packages: 89 org repos use them
- hashicorp/vault · Go · used here by my-svc · its packages: 43 org repos use them
- hashicorp/hcl · Go · its packages: 63 org repos use them
```

The catalog is the org's repo listing (hashicorp's 604 repos: 2.5 s), cached for a day. A phrase
is matched against each repo's name, description and topics, rarer words counting more, in
about a millisecond. INDEX is written from the caches only, so mapping a folder still makes no
network calls, and it holds names, languages and counts, never an org repo's description.

On phrases written without reading the org's repo list, the catalog found the repo first for
15 of 18 hashicorp phrases and 10 of 16 held-out grafana ones (13 in its top five). GitHub's
repository search, given the query an agent types for an org it doesn't know, found 12 of 18
and 8 of 16, in about 370 ms a search against cairn's 1.4 ms
([results](bench/published/2026-10-17-org-catalog.md)).

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
- **A bigger workspace isn't enough to make no map hard.** A pilot on OpenFaaS (38 real repos,
  2026-10-10, Sonnet 5.5, no map, one run per task) answered all ten of its tasks, for $0.07 a
  task with two or three searches each: every answer holds a literal string one workspace-wide
  search finds.
- **Neither are hard tasks** (2026-10-11 pilot, one run per cell). There are 11 of them, on
  OpenFaaS and One Login. No search for a task's own words finds its answer, and the prompt
  doesn't name the repo the answer is in. The agent has to read an identifier in code and follow
  it to a repo it works out itself.
  - Sonnet answered 11/11 in every condition.
  - Haiku answered 10/11 in every condition.
  - With a map, Sonnet's cost fell 17-19% on OpenFaaS and rose 19-29% on One Login.
  - The one failure a map clearly prevented: Haiku with no map never looked outside the repo it
    started in.
  - [bench/published/2026-10-11-hard-tasks.md](https://github.com/Moe1177/cairn/blob/main/bench/published/2026-10-11-hard-tasks.md)
    has the tasks, the definition and every failure.

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
cairn bench bench/suites/sockshop --harness codex --runs 3      # Codex instead of Claude Code
cairn bench-regrade bench/suites/sockshop bench/results/<stamp>.jsonl   # grade a log again
```

A task marked `hard: true` in a suite must be one that no search for the prompt's own words
answers, and whose prompt doesn't name the repo the answer is in. `cairn bench-reach` checks
this offline, and fails on a hard task that breaks either rule:

```bash
cairn bench-reach bench/suites/openfaas bench/suites/onelogin
```

With `--harness codex`, each run is `codex exec` in a read-only sandbox that ignores your Codex
config and rules and turns off every tool beyond reading the workspace (connected apps, plugins,
web search, sub-agents). The condition's context reaches it as developer instructions. A global
`AGENTS.md` in your Codex home would load into every run, so the benchmark won't start while
one is there.

The locate benchmark is offline and free: no agent runs. Each locator (grep, the code graph, and
the hybrid of both) answers every question in a suite's `locate.yaml`, and is scored on where the
answer file lands, how much text it returns and how long it takes.

```bash
cairn bench-locate bench/suites/sockshop bench/suites/networkx   # builds code graphs with graphify
cairn bench-locate bench/suites/shopverse --no-build --locators grep
```

The prior-art benchmark asks the question an agent has when it starts a feature in a large org:
does an implementation of this already exist, and where? Each suite's `prior_art.yaml` names a
GitHub org and lists feature tasks with files in it that already implement them, found and read
by hand. Every locator answers every task over GitHub's API, with nothing cloned, and is scored
on where the first answer file lands, how much text it returns and how long it takes. An org
holds more implementations than a key can list, so the report also says what share of each
locator's top five the key has judged; an unjudged hit is unknown, not wrong. It needs a GitHub
login (`gh auth login`, or `GH_TOKEN`), and code search allows 10 requests a minute, so a run
waits out the limit as it goes (about ten minutes for both suites). The `cairn` locator searches
with the terms an agent would pass, kept beside each key in `agent_terms.yaml`: a model wrote
them from the task alone (`--make-terms`), and nobody edits them.

```bash
cairn bench-prior-art bench/suites/aws-samples bench/suites/aws-samples-held
```

The packages benchmark asks whether an agent reaches for the org's own library. Each suite's
`packages.yaml` lists tasks with the org's packages that serve them. A model names the
libraries it would use, best first, from the task alone and after reading the list
`org_packages` returned (kept beside the key as `org_packages.md`, made with `--make-list`). It
does each twice, once with the org renamed, since a public org's libraries are in its training
data and a private org's aren't. The answers are kept in `agent_picks.yaml` (`--make-picks`),
so a run is repeatable and free.

```bash
cairn bench-packages bench/suites/hashicorp bench/suites/grafana
```

The repos benchmark asks how fast and how often a phrase finds the org repo it means. Each
suite's `repos.yaml` lists phrases with the repos they mean. cairn's catalog answers from the
listing kept beside the key (`org_catalog.json`, `--make-catalog`); GitHub's repository search
answers live, with the query a model types for each phrase (`agent_repo_queries.yaml`,
`--make-queries`), once knowing the org and once with its name masked.

```bash
cairn bench-repos bench/suites/hashicorp bench/suites/grafana
```

The link benchmark is offline and free too. Each suite's `links.yaml` lists the pairs of repos
that really link, written from the code and never from cairn's output; `cairn bench-links` scans
the suite and scores the links cairn shows (and, separately, its unconfirmed suggestions) as
pairs of repos: how many real links it finds, how many it finds that aren't real, and whether
it points them the right way.

```bash
cairn bench-links bench/suites/sockshop bench/suites/supabase-js
```

| Links cairn shows (2026-10-10) | real links | found | not real | precision | recall |
|---|---|---|---|---|---|
| Sock Shop (real, 9 repos) | 17 | 15 | 0 | 1.00 | 0.88 |
| Supabase JS (real, held out) | 5 | 5 | 0 | 1.00 | 1.00 |
| fleetline + shopverse (synthetic) | 26 | 26 | 0 | 1.00 | 1.00 |
| GOV.UK One Login (real AWS, 10 repos, held out) | 24 | 12 | 0 | 1.00 | 0.50 |
| OpenFaaS (real, 38 repos) | 88 | 48 | 4 | 0.92 | 0.55 |

What the misses and wrong links are:

- **Sock Shop:** orders reads users and carts through URLs the front-end puts in each order; no
  hostname for them appears in orders' code.
- **One Login:** cairn finds 11 of its 12 AWS links (SQS queues, DynamoDB tables and SSM
  parameters behind stack parameters, shared Lambdas, KMS keys, exports). It misses the HTTP
  links (core calling each credential issuer, known from Pact contracts; stubs standing in for
  services) and one export whose stack name only a deploy script sets.
- **OpenFaaS:** it was held out until its first run showed 19 wrong links, all READMEs telling
  readers to run `faas-cli`, and missed Go modules outside a repo's root (`gateway/go.mod`).
  Both are fixed (it scored 0.70 precision and 0.51 recall before), so it is now tuned on, not
  held out. Most misses left are images used as Dockerfile base images, HTTP clients of the
  gateway, and the function store's JSON catalogue.

Unconfirmed suggestions add one or two wrong links in most suites (a table name two repos share,
look-alike repos).

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

cairn **collects no telemetry**, and mapping your folder makes **no network calls**. It talks
to a server only when you ask it to:
- with `orgs:` in the config, `find_similar`, `read_org_file`, `org_profile`, `org_packages`,
  `cairn similar`, `cairn org-profile` and `cairn org-packages` call your code host's API, and
  so do `resolve_repo` and `repo_card` once a day, to read the org's repo listing (with your own login: on GitHub `GH_TOKEN`, or
  `GH_ENTERPRISE_TOKEN` for an Enterprise host, else `gh auth token`; on GitLab `GITLAB_TOKEN`
  or `GITLAB_ACCESS_TOKEN`, else `glab config get token`). The token goes only to the host its
  org is configured on. They send the search terms (the task's own words when no terms are
  given) and the org's name, and read back matching files; nothing from your local repos is sent.
  They only ever reach the orgs in your config: a call naming another org, or another owner's
  repo, is refused, and a search hit from outside the org is dropped;
- `cairn bench-prior-art` calls the same API, and with `--make-terms` runs the `claude` CLI
  (with `--make-profile`, it also reads the org's profile); `cairn bench-packages` reads the
  org's packages with `--make-list` and runs the `claude` CLI with `--make-picks`; `cairn
  bench-repos` reads the org's listing with `--make-catalog`, searches GitHub's repositories,
  and runs the `claude` CLI with `--make-queries`;
- `cairn deep enable` runs your package installer (uv, pipx or pip) to add graphify;
- `cairn bench`, `cairn bench-locate` and `cairn bench-links` fetch their pinned benchmark repos
  with git, and `cairn bench` runs the `claude` CLI.

See [SECURITY.md](https://github.com/Moe1177/cairn/blob/main/SECURITY.md) for the threat model and
how to report a vulnerability.

## Reference

### Commands

| Command | What it does |
|---|---|
| `cairn init` | Scan, then offer to add the index to Claude Code |
| `cairn scan [--full] [--verbose]` | Map every repo under the folder into `.cairn/` |
| `cairn refresh [--no-deep]` | Re-read only repos whose HEAD or working tree changed, and rebuild stale deep indexes |
| `cairn deep enable` / `cairn deep build REPO…\|--all\|--stale [-w PATH]` | Build graphify code indexes so `query` also names symbols (optional extra) |
| `cairn deep status` / `cairn deep clear [REPO…]` | List deep indexes (fresh or stale) / delete them |
| `cairn status` | What cairn knows, unconfirmed links, missing or stale summaries |
| `cairn annotate-edge KEY --confirm\|--reject [--why TEXT]` | Settle a relationship |
| `cairn set-summary REPO TEXT [--alias NAME]` | Save a summary (`-` reads stdin) |
| `cairn install <claude\|codex\|gemini\|cursor\|all>` | Load cairn into an agent harness |
| `cairn uninstall <name\|all>` | Remove it again |
| `cairn hooks install\|uninstall` | Opt-in git hooks that refresh after commits and merges |
| `cairn serve` | The MCP server (harnesses start it for you) |
| `cairn links [REPO]` | Which repos a repo is linked to, one line each with its direction; the repo you're in by default (`--evidence`, `--all`, `--json`) |
| `cairn context` | What a Claude Code session should know about its folder: the index, or an offer to build a map (the plugin's session hook runs it) |
| `cairn similar TASK --terms A,B` | Where your org already implemented a feature, over the host's API |
| `cairn org-profile [--refresh]` | Your org's stack, read from its recently pushed repos over the host's API (cached for a week) |
| `cairn org-packages [NAME] [--query WORDS] [--refresh]` | Your org's own packages: where each is defined and which repos use it (cached for a day) |
| `cairn bench SUITE` | Run the benchmark harness |
| `cairn bench-locate SUITE...` | Score grep, graph and hybrid locate offline |
| `cairn bench-links SUITE...` | Score cairn's links against each suite's real ones, offline |
| `cairn bench-prior-art SUITE...` | Score finding an org's existing implementation of a feature, over the host's API (no clone) |
| `cairn bench-packages SUITE...` | Score whether an agent names the org's own library for a task, from memory and from `org_packages` |
| `cairn bench-repos SUITE...` | Score finding an uncloned org repo from a phrase: cairn's catalog against GitHub's repository search |
| `cairn bench-regrade SUITE LOG` | Grade a finished run's log again with today's grading |
| `cairn bench-reach SUITE...` | Which tasks a search for the prompt's own words answers, offline; fails on a hard task that one does |
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
6. ✅ Deploy config: which repo creates each AWS resource and which use it (Terraform,
   CloudFormation/SAM, Serverless Framework, CDK, Lambda, SSM), and Railway, Fly.io and Render
   services (0.8).
7. ✅ Codex in the benchmark, Maven and Gradle, real-world link benchmarks, draft summaries.
8. ✅ Harder benchmark tasks: 11 tasks that no search for their own words answers, checked by
   `cairn bench-reach`. Without a map, Sonnet still answered all of them.
9. ✅ Prior art across an org too big to clone: `find_similar` and `read_org_file` over GitHub's
   API, measured by `cairn bench-prior-art` on ~9,300 repos.
10. ✅ The org's stack: `org_profile` lists what the org's active repos build with, in about
    15 s and from a cache after. Writing search terms from it didn't find more prior art, and
    the benchmark says so.
11. ✅ The org's own packages across repos nobody cloned: `org_packages` says where each is
    defined, which repos use it and which files call it, measured by `cairn bench-packages`.
12. ✅ Org repos nobody cloned: `resolve_repo` and `repo_card` reach them from the org's
    catalog, and INDEX lists those the workspace depends on, measured by `cairn bench-repos`.
13. ✅ GitLab (gitlab.com and self-managed, groups with subgroups) for every org feature.
14. Orgs on any git host, from a list of repo URLs.
15. Benchmark sessions that start with only their own repo in view, the way a session opened in
    one repo does.

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
