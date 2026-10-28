# Sessions that start in one repo (2026-10-27)

**Question.** Every earlier benchmark put the whole workspace on disk. A real session usually
starts in one repo, and the org's other repos aren't cloned. Do cairn's org tools get an agent to
the answer in those repos, and how close does that come to having every repo on disk?

**Answer, from a pilot (one run per cell):**
- **Without the org tools, a session in one repo almost never answers.** With no map or with
  cairn's INDEX, both models answered 1 of the 11 hard tasks, the one whose answer sits in a copy
  vendored into the starting repo.
- **With them, it answers most.** Sonnet 5.5 answered 4 of 11 with the org tools as they were, and
  9 of 11 after the two changes this benchmark led to. Haiku 5.5 went from 5 to 7. With every repo
  on disk, Sonnet answers 11 and Haiku 10.
- **It takes longer.** Sonnet's median session took 23 s from one repo and 18 s with every repo
  on disk; it cost $0.127 a task against $0.093.

## Method

- **`cairn bench --scope repo`.** Each task's session runs in a workspace holding only its
  starting repo. The suite's org is configured, and the org's catalog, packages and profile are
  read into the cache once before any session, as for a user who has used cairn with the org
  before. Answers are graded against the whole pinned workspace, as before.
- **Kept out of the other repos.** Claude Code's file tools are allowed only inside the session's
  workspace, and the session is denied the run's other folders, the suite (which holds the
  answers) and every other session's workspace. A probe session tried Read, Grep and Glob outside
  its workspace; all three were refused.
- **Conditions.** A (no map), C (cairn's INDEX, with its org section) and E (INDEX + cards + MCP
  server). Only E has the org tools, so A and C can name the other repos but not read them; a task
  whose answer lies in another repo is out of their reach by design.
- **Compared with every repo on disk:** condition E, `--scope workspace`.
- **Tasks.** The 11 hard tasks of [2026-10-11](2026-10-11-hard-tasks.md): 6 on OpenFaaS and 5 on
  One Login. No search for a hard task's own words finds its answer, and its prompt doesn't name
  the repo the answer is in.
- **Models:** Haiku 5.5 and Sonnet 5.5, Claude Code 2.1.311, one run per cell.
- **Reading the org's latest commit.** The org tools read each repo's default branch; the suite
  pins older commits. Before the sessions, the run checks each answer file outside the starting
  repo on the org, and each answer keyword those files held. One had moved: of-watchdog's version
  in golang-http-template's Dockerfile, `0.12.4` at the pinned commit and `0.12.5` today. All six
  E sessions from one repo gave `0.12.5` for `delay-function-template`, which is right for
  what it read and fails the key. The table counts those as failures; "with drift" counts them as
  answers.

## Results

Hard tasks answered, of 11 (6 OpenFaaS + 5 One Login), with mean file recall and the median
session:

| | Haiku 5.5 | | | Sonnet 5.5 | | |
|---|---|---|---|---|---|---|
| **Setup** | **Answered** | **Recall** | **Median** | **Answered** | **Recall** | **Median** |
| One repo, no map (A) | 1 | 0.33 | 25 s | 1 | 0.25 | 21 s |
| One repo, INDEX (C) | 1 | 0.35 | 23 s | 1 | 0.35 | 17 s |
| One repo, org tools as they were (E) | 5 (6 with drift) | 0.59 | 28 s | 4 (5) | 0.62 | 24 s |
| + `read_org_file` lists folders | 5 (6) | 0.63 | 26 s | 8 (9) | 0.88 | 31 s |
| + `search_org` | **7 (8)** | 0.76 | 27 s | **9 (10)** | 0.97 | 23 s |
| Every repo on disk (E) | 10 | 0.91 | 19 s | 11 | 1.00 | 18 s |

Cost per task, Sonnet: $0.087 (A), $0.123 (E as it was), $0.127 (E with both changes), $0.093
(every repo on disk). Haiku: $0.008 to $0.016 throughout. Each row's "+" adds to the one above.

One run per cell: a single task flipping is within noise. The gaps between the first two rows
and the rest, and between Sonnet's first and last E rows (4 to 9), are the ones to trust.

## What the failures showed, and what changed

We read every failed answer of the first E row before changing anything.

**A wrong path in an uncloned repo was a dead end.** An agent can't list a repo it hasn't cloned.
Sonnet, asked which chart file mounts the build secret, tried nine names under
`chart/pro-builder/templates/` (`deployment.yaml`, `pro-builder-dep.yaml`, ...); the file is
`deployment.yml`. It stopped there and asked for permission to call `gh api`. In a smoke run,
Haiku asked for `readConfig.go`; the file is `readconfig.go`.

`read_org_file` now answers a folder with what it holds, and a path that isn't there with the
files it most likely meant: the same path in another case, then files of the same name anywhere,
then paths spelled alike, or else what the nearest existing folder holds. Sonnet then answered 8
instead of 4.

**"Who uses this?" found nothing, though cairn could answer it.** Asked which templates import
the core stack's `ApiKey1` and `ApiKey2`, or what reads `gateway_function_invocation_total`,
agents called `find_across`. It knows only the repos on disk, so it answered with nothing, and the
agents stopped. `find_similar` runs the org's code search and answers both in under a second:
every template that imports the keys, and every file that names the metric. No session called it: it
reads as a tool for prior art before building a feature.

`search_org(terms)` is the same search, worded as uses ("Uses in govuk-one-login of `ApiKey1`").
`find_across` now ends with a pointer to it when a GitHub or GitLab org is configured. With it,
`retire-core-api-keys` went from failed to answered for both models.

**The grader failed answers that read the org correctly.** Agents reading the org write a repo
and a path apart: "`openfaas/faas`: `gateway/metrics/metrics.go`", or "in the
`openfaas/faas-middleware` repo, at `oauth/config.go:91`". The grader gave those paths to the
starting repo, where they aren't files. A bare path that isn't a file of the starting repo now
belongs to the first repo its line names that has it. Every log above was regraded with it, in
every condition alike; it changed 15 of 132 grades, eight of them from failed to answered. On the
2026-10-11 hard-task logs it changes one run (Haiku, no map, `remote-build-signature`), from
failed to answered.

## What is still missing

- **Haiku doesn't always reach for the org tools.** Of its three One Login failures with both
  changes, one never left the starting repo; in the other two it read the org but didn't find
  the hop. One Login from one repo is where the gap remains: 2 of 5, against 4 of 5 with every
  repo on disk.
- **Reading the org is slower than reading disk.** Sonnet's mean session from one repo was 32 s
  against 18 s, with more calls (each a request to the host).
- **Redaction hides names that aren't secrets.** cairn masks values next to key-like names
  before an agent sees a file. That hides a Kubernetes secret's *name* (`secretName:
  payload-secret`) and the CloudFormation `Type:` line under `ApiKey1:`. Two answers hedged
  because of it. No task turned on it.
- **One run per cell.** Repeating the E rows would firm up the per-task differences.

## Reproduce

```bash
cairn bench bench/suites/openfaas --scope repo --conditions A,C,E --model sonnet \
  --tasks async-channel-ignored,catalogue-hash-entry,remote-build-signature,function-sign-in-callback,delay-function-template,rename-invocation-counter
cairn bench bench/suites/onelogin --scope repo --conditions A,C,E --model sonnet
cairn bench bench/suites/onelogin --conditions E --model sonnet   # every repo on disk
cairn bench-regrade bench/suites/onelogin bench/results/<stamp>.jsonl
```

`--scope repo` needs a suite with `org:` in its `suite.yaml` and the Claude Code harness (Codex
can't be kept out of the other folders).
