# Hard tasks: answers no search for the prompt's words finds (2026-10-11)

**Question.** The 2026-10-10 OpenFaaS pilot answered every task without a map, for $0.07 a task
and two or three searches each, because every answer held a literal from its prompt. Does cairn
matter once that shortcut is gone?

**Answer, from a pilot (one run per cell):** not measurably. Sonnet 5.5 and Haiku 4.5 answered
these tasks as well with no map as with one, and a map didn't cost less overall. The only failure
a map clearly prevented was Haiku, with no map, not looking outside the repo it started in.

## What makes a task hard

A task is **hard** when both of these hold. `cairn bench-reach SUITE...` checks them offline and
exits 1 when a task marked `hard: true` breaks either:

1. **No search for the prompt's own words leads to the answer.** The check runs every search an
   agent could make from the prompt alone, case-insensitively over every file's text and path
   (vendored copies and generated output excepted):
   - each word, quoted string and route;
   - each pair of neighbouring words joined as code would join them (`queue worker` ->
     `queue-worker`, `queue_worker`, `queueworker`);
   - each part of a compound (`a.b.c`, `repo/path`).

   A search that matches 50 files or fewer is one an agent can read through. The task fails the
   check if those searches, taken together, find 80% of its answer files (the grading pass mark).
2. **The prompt doesn't name the repo the answer is in.** A prompt term found in the names of at
   most two repos singles them out. If one of those repos holds an answer file (other than the
   repo the agent starts in), the task fails the check. "The queue worker" names
   nats-queue-worker: an agent that lists the workspace goes straight there.

So a hard task's answer takes an identifier read from code first, such as an image, a stack
export, a Pact provider name, a NATS subject, a metric's parts or a URL in config. The agent then
follows it into a repo it has to work out.

**Every task in the earlier suites fails one of the two conditions.** Most are answered by one
search. The rest name the repo the answer is in. That fits with Sonnet succeeding on 99-100% of
them in every condition.

## The tasks

11 tasks, written by agents from the code alone: they ran no cairn command and read none of its
output. Each task's comment in `suite.yaml` gives the chain of hops, the bridging identifiers, and
why each near-miss file is out. Four keys were spot-checked against the code by hand.

| Suite | Task | Starts in | The hop no search makes |
|---|---|---|---|
| OpenFaaS | async-channel-ignored | faas-netes | chart value -> env var the queue worker never reads (a hard-coded subject) |
| OpenFaaS | catalogue-hash-entry | faas-cli | catalogue URL -> store entry -> generic image built elsewhere (trap: a look-alike shasum image) |
| OpenFaaS | remote-build-signature | faas-cli | go-sdk signing code -> secret name -> the pro-builder chart's mount |
| OpenFaaS | function-sign-in-callback | of-watchdog | `oauth_enabled` -> faas-middleware's oauth config and callback route |
| OpenFaaS | delay-function-template | store-functions | `lang:` + template source URL -> golang-http-template's server and watchdog pin |
| OpenFaaS | rename-invocation-counter | faas-netes | alert query -> metric whose definition is assembled from three parts |
| One Login | dl-front-session-handlers | ipv-cri-dl-front | stack export -> private API routes -> common Lambdas by function name |
| One Login | dl-token-contract-verification | ipv-cri-dl-api | Pact provider name -> consumer tests -> CI matrix -> env-driven provider test |
| One Login | retire-core-api-keys | ipv-cri-common-infrastructure | export suffix -> the three templates that import the keys |
| One Login | cimit-stub-endpoints | ipv-core-back | client paths + config URL -> the stub's OpenAPI routes -> handlers |
| One Login | async-result-queue-origin | ipv-core-back | cross-account queue ARN -> face-to-face stub -> queue stub that creates it |

## Method

- **Runs:** `cairn bench`, conditions A (no map), C (cairn's INDEX) and E (INDEX + cards + MCP
  server), one run per cell, Claude Code 2.1.296.
- **Workspaces:** OpenFaaS (38 repos, its 6 hard tasks only) and One Login (10 repos, all 5
  tasks).
- **Models:** Sonnet 5.5 and Haiku 4.5.
- **Grading:** the same deterministic file and keyword grading as before, with the fix below.
  Every run was regraded with `cairn bench-regrade`.

**Grading fix.** Reading the failed answers turned up three correct answers the old grading
failed:
- One put the repo and the path in separate table columns.
- Two wrote paths relative to a folder named once above them ("all under
  `ipv-stubs/di-ipv-cimit-stub/lambdas/src/internal-api/`").

Grading now:
- gives a bare path to the repo its table row names;
- failing that, gives it to the one workspace file the path is the end of, if exactly one file
  ends that way.

This applies to every condition alike. `cairn bench-regrade SUITE LOG` grades an earlier log
again. The remaining failures were read one by one, and each is a real miss.

## Results

| Model | Suite | Success A / C / E | Cost per task A / C / E (USD) |
|---|---|---|---|
| Sonnet 5.5 | OpenFaaS (6) | 6/6 / 6/6 / 6/6 | 0.102 / 0.082 / 0.084 |
| Sonnet 5.5 | One Login (5) | 5/5 / 5/5 / 5/5 | 0.098 / 0.116 / 0.126 |
| Haiku 4.5 | OpenFaaS (6) | 6/6 / 5/6 / 6/6 | 0.0087 / 0.0087 / 0.0093 |
| Haiku 4.5 | One Login (5) | 4/5 / 5/5 / 4/5 | 0.0111 / 0.0116 / 0.0120 |

**The failures (each read in full):**

| Model | Condition | Task | What went wrong |
|---|---|---|---|
| Haiku | A | async-result-queue-origin | Stayed in its own repo: "the stub's own code is not in this repo, so I cannot confirm". C and E found the stub. |
| Haiku | C | catalogue-hash-entry | Took the trap: named the look-alike shasum Dockerfile, not the image the catalogue deploys. |
| Haiku | E | dl-token-contract-verification | Found the CI matrix and the consumer tests, but didn't open the provider test the matrix runs. |

**Searches stayed few.** Agents averaged 3-7 searches and 1-4 file reads per task in every
condition. Only one of the 22 runs with the MCP server (E) called a cairn tool.

## What this shows

- **Taking away the shortcut didn't make no map fail.** Both models follow a hop from code to a
  repo the prompt doesn't name in a few searches: read the identifier, search the workspace for
  it. At 10-38 repos, one search across the whole workspace is cheap enough that a map adds
  little.
- **Cost moved both ways.** With a map, Sonnet was 17-19% cheaper on OpenFaaS and 19-29% dearer
  on One Login. Haiku's costs were within 8% across conditions. One run per cell can't tell these
  apart from noise.
- **A map helps when the agent wouldn't look outside its own repo.** Haiku with no map treated
  "not in this repo" as the end of the search, and the INDEX told it which sibling to read. A
  workspace the agent can search all at once hides this. In real use, a session opened in one
  repo may never look at its siblings.
- **The MCP tools went unused.** In E, agents read the INDEX and cards and then searched.

## Next

- A run with 3 runs per cell, which the 11 tasks allow, to put intervals on the cost differences.
- Tasks where the agent starts with only its own repo in view, the way a session opened in one
  repo does. That's where the one map-dependent failure came from.

## Reproduce

```bash
cairn bench-reach bench/suites/openfaas bench/suites/onelogin     # offline: which tasks are hard
cairn bench bench/suites/onelogin --conditions A,C,E --model sonnet
cairn bench bench/suites/openfaas --conditions A,C,E --model sonnet --tasks \
  async-channel-ignored,catalogue-hash-entry,remote-build-signature,function-sign-in-callback,delay-function-template,rename-invocation-counter
cairn bench-regrade bench/suites/onelogin bench/results/<stamp>.jsonl
```
