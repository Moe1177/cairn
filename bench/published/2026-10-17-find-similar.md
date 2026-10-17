# find_similar: prior art in a 9,300-repo org (2026-10-17)

Offline: no agent runs and nothing is cloned. `cairn bench-prior-art` asks each locator, over
GitHub's API, for the files in `aws-samples` (~9,300 repos) that already implement a feature, and
scores where the first known implementation lands. Two keys:

- **dev** (`bench/suites/aws-samples`, 18 tasks): written first; cairn's ranking was tuned while
  looking at it.
- **held** (`bench/suites/aws-samples-held`, 12 tasks): written after the tuning, run once, with
  nothing about the method changed after.

Each key lists files found by searching for code identifiers (never the task's words) and
confirmed by reading them. *Literal* tasks name the technology ("verify Stripe webhook
signatures"); *vocabulary* tasks describe the need in words the code rarely uses ("stop any
single client from flooding our API").

Locators, each over the same org:

- `search-raw`: the task's own words as one code search.
- `search-terms`: three of the task's words, as an agent's first search might be.
- `cairn`: `find_similar` with the terms an agent would pass it. Claude Haiku wrote them from the
  task alone (`agent_terms.yaml` beside each key; nobody edited them). Three searches run at once;
  hits merge by reciprocal rank; vendored copies, docs, configs and tests are weighed down or
  dropped.

## Results

hit@k: share of tasks with a known implementation in the top k. MRR over the top five. ms: wall
time per task, rate-limit waits excluded (median).

| split | locator | category | n | hit@1 | hit@3 | hit@5 | MRR@5 | ms |
|---|---|---|---|---|---|---|---|---|
| dev | search-raw | all | 18 | 0.00 | 0.06 | 0.11 | 0.03 | 380 |
| dev | search-terms | all | 18 | 0.11 | 0.22 | 0.28 | 0.17 | 290 |
| dev | **cairn** | literal | 7 | 0.57 | 0.86 | 0.86 | 0.67 | 557 |
| dev | **cairn** | vocabulary | 11 | 0.64 | 0.91 | 1.00 | 0.76 | 569 |
| dev | **cairn** | all | 18 | **0.61** | **0.89** | **0.94** | **0.72** | 563 |
| held | search-raw | all | 12 | 0.00 | 0.08 | 0.08 | 0.03 | 640 |
| held | search-terms | all | 12 | 0.08 | 0.17 | 0.17 | 0.12 | 880 |
| held | **cairn** | literal | 5 | 0.60 | 0.80 | 1.00 | 0.75 | 722 |
| held | **cairn** | vocabulary | 7 | 0.43 | 0.71 | 0.71 | 0.55 | 598 |
| held | **cairn** | all | 12 | **0.50** | **0.75** | **0.83** | **0.63** | 659 |

## How to read it

- **The words are the whole game.** One plain search of three task words (`search-terms`) finds
  prior art for 5 tasks in 18 and 2 in 12; with
  the code's own words, and three of them at once, cairn finds it for 17 of 18 and 10 of 12. No
  vocabulary task is found by plain search on held; cairn finds 5 of 7.
- **Fast enough to call before every feature.** Three parallel searches take about 0.6 s,
  barely more than one. Code search allows 10 requests a minute: a burst of three `find_similar`
  calls fits; a fourth in the same minute waits.
- **Judging was pooled, and it matters.** A 9,300-repo org holds far more implementations than a
  key can list. After each run, every locator's top five was pooled and each code file read and
  judged (accepted or rejected) by the same rules; the ranking was not changed afterwards.
  Before judging, held read 0.25 for cairn: most of its hits were real implementations nobody had
  listed yet. Plain search's unjudged hits were mostly READMEs, notebooks and configs, which a
  key never counts.
- **dev is optimistic; held is the number to quote.** dev was judged over three rounds while the
  ranking was tuned on it. One tuning idea, boosting files named after a search term
  (`circuit_breaker.py`), lost on dev (hit@1 0.61 → 0.44: it lifted `config.py` for the term
  `AppConfig`) and was dropped.
- **The misses point at the next lever: the org's conventions.** Both held misses got terms from
  outside this org's stack: for "keep a count many workers bump at once" Haiku searched
  `AtomicInteger`, and for "have old records disappear" `expireAfterSeconds` (MongoDB). For "only
  one worker at a time" it searched `pg_try_advisory_lock` and found a lock only at rank 2. This
  org does all three with DynamoDB. An agent that knew the org's stack would search for
  `UpdateExpression ADD`, `timeToLiveAttribute` and a DynamoDB lock: that is the conventions
  layer, next on the roadmap.
