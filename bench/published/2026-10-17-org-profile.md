# org_profile: does knowing the org's stack find more prior art? (2026-10-17)

No. It is a useful summary of what the org builds with, but search terms written after reading it
did not find more of the org's existing implementations than terms written from the task alone.

## What was tested

`org_profile` reads the 200 most recently pushed repos of `aws-samples` over GitHub's API (their
file trees and up to three manifests each) and writes a few lines on what they use: languages,
datastores, queues, frameworks, auth, test and deploy tools, the most used libraries, and the
org's own shared packages. For `aws-samples` it took 14.2 s, made about 800 requests, and came to
2,900 characters (`bench/suites/aws-samples/org_profile.md`).

The idea was that the misses in the [find_similar results](2026-10-17-find-similar.md) came from
terms outside the org's stack (`AtomicInteger` and MongoDB's `expireAfterSeconds` in an org that
mostly uses DynamoDB). So `cairn bench-prior-art` gained a `cairn-profile` locator. It runs the
same `find_similar` with terms Claude Haiku wrote after reading the profile and the task
(`agent_terms_profile.yaml` beside each key, never edited). The `cairn` locator's terms were
written from the task alone, as before.

## Method

- **Tuned on dev, run once on held.** The first profile ended with "search this stack's words".
  On dev that cost the literal tasks, which already name their technology (hit@1 0.29 against
  0.57). The guidance became "when the request names a technology, search for its own calls;
  otherwise this stack's". A held run with the first wording was stopped before it produced
  anything, and held then ran once with the final wording.
- **Pooled judging.** After each run, every unjudged file in either locator's top five was read
  and judged under the key's written rules: accept only code that implements the task, any
  technology that achieves it. This round was judged by Claude subagents reading each file.
  Two of their rejections (Cognito JWT verifiers) were turned into accepts, to match files the
  key already accepted. Both splits are now fully judged (judged@5 = 1.00).

## Results

hit@k: share of tasks with a known implementation in the top k. MRR over the top five. ms: median
wall time per task, rate-limit waits excluded.

| split | locator | n | hit@1 | hit@3 | hit@5 | MRR@5 | ms |
|---|---|---|---|---|---|---|---|
| dev | cairn | 18 | 0.61 | 0.94 | 1.00 | 0.75 | 680 |
| dev | cairn-profile, first wording | 18 | 0.56 | 0.94 | 1.00 | 0.75 | 612 |
| dev | cairn-profile, final wording | 18 | 0.67 | 0.94 | 0.94 | 0.79 | 548 |
| held | **cairn** | 12 | **0.67** | 0.83 | **0.92** | **0.77** | 687 |
| held | cairn-profile | 12 | 0.58 | 0.83 | 0.83 | 0.68 | 752 |

By category on held: literal 5 tasks (cairn 1.00 hit@5, profile 0.80), vocabulary 7 (both 0.86).

## How to read it

- **Held says no.** The profile's terms missed one task the plain terms found (Google sign-in:
  they swapped `identity_provider=Google` and `accounts.google.com`, which name Google, for
  `create_identity_provider` and `signInWithRedirect`, which don't). Their only gains came on dev, where the wording was tuned.
- **The motivating misses were partly unjudged hits.** The [find_similar results](2026-10-17-find-similar.md)
  counted "records expire" as a miss for the plain terms. Judged now, their `pg_cron` search finds
  purge jobs this org really runs. Both locators still miss "a count many workers bump at once".
  The profile's terms moved to DynamoDB words (`UpdateExpression`, `update_item`), but those
  matched ordinary SET updates, not ADD counters.
- **The find_similar numbers moved too.** On today's run, with every hit judged, `cairn` reads
  0.92 hit@5 and 0.77 MRR on held, against 0.83 and 0.63 published this morning. Some of that is
  newly judged hits and some is GitHub's index changing between runs. A pooled key only grows,
  so later runs read a little higher for every locator.
- **What ships.** `org_profile` stays: what the org builds with is context an agent writing new
  code should have, and it costs a cached read after the first 15 s. cairn doesn't tell agents to
  write search terms from it.
