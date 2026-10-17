# Prior art in a large org: the baseline (2026-10-17)

Offline: no agent runs and nothing is cloned. `cairn bench-prior-art` asks GitHub's code search,
over the API, to find the files in `aws-samples` (~9,300 repos) that already implement each of 18
feature tasks, and scores where the first answer file lands. The key lists implementations found
by searching for code identifiers and confirmed by reading each file; the tasks are phrased
without those identifiers.

Two baselines, both one search per task:

- `search-raw`: the task's own words, as pasting the request into search would do.
- `search-terms`: three of the task's words (cairn's term extraction), as an agent's first search
  might.

| locator | category | n | hit@1 | hit@5 | MRR | tokens | ms (median) |
|---|---|---|---|---|---|---|---|
| search-raw | literal | 7 | 0.00 | 0.00 | 0.00 | 505 | 412 |
| search-raw | vocabulary | 11 | 0.00 | 0.00 | 0.00 | 467 | 620 |
| search-terms | literal | 7 | 0.14 | 0.14 | 0.14 | 816 | 604 |
| search-terms | vocabulary | 11 | 0.00 | 0.00 | 0.00 | 838 | 1172 |
| search-terms | all | 18 | 0.06 | 0.06 | 0.06 | 829 | 672 |

What it shows:

- **Search is fast and the answers exist, but plain search doesn't reach them.** One task in 18
  (the Stripe webhook check, whose task names the library) found a known implementation in its
  top five. No vocabulary task did: "stop any single client from flooding our API" shares no
  words with `class RateLimiter`.
- **The top five is mostly noise.** READMEs, notebooks, changelogs, and vendored copies of
  libraries (`botocore/signers.py`, `.venv/Lib/site-packages/...`) fill it. Filtering and ranking
  hits is a lever of its own, separate from finding better words to search for.
- **Read the zeros with the judged share in mind.** Only 4–11% of the top fives were judged; some
  unjudged hits may be valid implementations the key doesn't list
  (`aws-ai-phi-deidentification/.../idp-phi-redact-doc.py` for PII redaction, say). Judging them
  would lift both baselines a little, not change the picture.
- **Rate limits shape speed.** Code search allows 10 requests a minute: the run waited 160 s in
  all, and a locator that searches several times per task trades accuracy for that budget.
