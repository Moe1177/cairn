# The org catalog: finding a repo nobody cloned, from a phrase (2026-10-17)

An agent hears "the terraform provider for AWS" or "the kubernetes operator that syncs secrets"
and needs the org repo it means, which isn't on disk. cairn's catalog of the org's repos found
it first more often than GitHub's repository search, in about 1 ms instead of about 370 ms.
GitHub's search did better only when the agent already knew the org's repo names.

## What was tested

The catalog is the org's repo listing (names, descriptions, topics, languages), read in one
request per 100 repos (hashicorp's 604: 2.5 s) and cached for a day. `resolve_repo` matches a
phrase against it: each word of the phrase found in a repo's name, description or topics counts
by how rare it is in the org, double in the name; plurals and -ing/-ed endings are dropped, and
neighbouring words are also tried joined ("data plane": dataplane).

Each suite's `repos.yaml` lists phrases with the active repos they mean, written from what each
product does without reading the org's repo list or descriptions, then checked to exist. Two
dev drafts named archived repos (terraform-cdk, boundary) and were dropped before any run.

Three locators answer every phrase:

- **cairn**: `resolve_repo`'s catalog search, given the phrase (from the listing kept beside the
  key as `org_catalog.json`);
- **github-search**: GitHub's repository search in the org, given the 1 to 3 word query Claude
  Haiku types for the phrase;
- **github-search-masked**: the same, with Haiku asked about an org renamed `veltrix`. Haiku
  knows hashicorp's and grafana's repo names (asked about hashicorp, it typed `consul-template`
  and `go-tfe`); no model knows a private org's, and masking stands in for that.

Haiku's queries are kept in `agent_repo_queries.yaml` and never edited.

## Method

- **Tuned on dev, run once on held.** On dev, the first version found 13 of 18 first. Joined
  neighbours ("VS Code": vscode), `k8s` read as kubernetes, and a precomputed word count per
  catalog took it to 16 of 18 and from about 11 ms to 1.4 ms a search. Held, written before
  any dev run, was then run once.
- **A fix after held.** A review found that "services" and "service" didn't meet (the plural
  stripped as "-es"). Fixed, dev went to 15 of 18 first ("kubernetes resources" now also matches
  repos about AWS resources), and held, scored again with the shipped code, was unchanged
  (10 of 16 first, 13 in the top five). The table shows the shipped code.
- **No judging.** Each phrase means one repo (or names the ones it may mean).

## Results

hit@k: share of phrases whose repo is among the first k. Median ms per phrase: cairn's is the
search on a loaded catalog; GitHub's is one API request.

| split | locator | n | hit@1 | hit@5 | MRR@5 | median ms |
|---|---|---|---|---|---|---|
| dev (hashicorp) | **cairn** | 18 | **0.83** | 0.94 | 0.88 | 1.4 |
| dev (hashicorp) | github-search | 18 | 0.94 | 0.94 | 0.94 | 406.6 |
| dev (hashicorp) | github-search-masked | 18 | 0.67 | 0.67 | 0.67 | 381.7 |
| held (grafana) | **cairn** | 16 | **0.62** | **0.81** | 0.70 | 1.2 |
| held (grafana) | github-search | 16 | 0.88 | 0.88 | 0.88 | 413.3 |
| held (grafana) | github-search-masked | 16 | 0.50 | 0.50 | 0.50 | 356.0 |

The first `resolve_repo` of a day also reads the listing (3.6 s for hashicorp in a smoke test,
token lookup included); later ones answer from memory in milliseconds.

## How to read it

- **For a private org, cairn's catalog is the better first step.** Against GitHub's search with
  the queries an agent types for an org it doesn't know, cairn found more on both splits (held:
  10 against 8 first, 13 against 8 in the top five), about 300 times faster, and with no rate
  limit (GitHub's search allows 30 a minute).
- **Held fell well below dev.** Dev was tuned; held is the number to quote. Its misses show two
  weaknesses, left for a later round with fresh phrases:
  - short words don't meet their longer forms ("log" against "logs" and "logging"), so Loki
    ("Like Prometheus, but for logs") wasn't found for "the log aggregation system";
  - nothing favours an org's main repos: `mcp-grafana` ("MCP server for Grafana") ranked below
    smaller MCP repos, and the helm-charts repo has no description at all. Stars, which the
    listing already carries, would be a fair tie-breaker.
- **GitHub's search wins when the agent knows the names.** Given the org's real name, Haiku
  typed exact repo names and GitHub found 0.88 to 0.94 first. That knowledge exists only for
  public orgs.
- **What else it gives.** `repo_card` on an uncloned repo adds what the package index knows (the
  packages it defines, the org libraries it uses, the workspace repos depending on it), and
  INDEX lists the uncloned org repos the workspace depends on. Those come from the same caches
  and aren't scored here.
