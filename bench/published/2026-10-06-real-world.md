# Real-world benchmark (2026-10-06)

**Setup.** 4 workspaces, 28 tasks, 5 conditions, 2 models, 3 runs per cell: 840 runs, all graded
deterministically against answer keys (file recall >= 0.8 plus required facts).

| Workspace | Repos | Tasks | Notes |
|---|---|---|---|
| sockshop | 9 | 8 | Weaveworks Sock Shop microservices (Apache-2.0), pinned commits. cairn's new link types were developed on it. |
| supabase-js | 6 | 6 | Supabase JS client family before its 2025 monorepo merge (MIT/Apache-2.0), pinned commits. **Held out**: never used to tune cairn. |
| fleetline | 15 | 8 | Synthetic, with look-alike distractors. |
| shopverse | 6 | 6 | Synthetic. |

Conditions: **A** no map, **B** a hand-written related-repos doc (the strong human baseline),
**C** cairn INDEX only, **D** INDEX + cards, **E** D + cairn's MCP server.

Runs: headless Claude Code (`claude -p`), read-only tools, a fresh isolated workspace per run, no
user memory or rules loaded.
- `--model haiku`: Claude Code 2.1.290 at the last invocation (these logs predate per-invocation
  headers, so earlier invocations' versions weren't recorded), cairn 0.5.0 code, models seen: claude-haiku-4-5-20251001
- `--model sonnet`: Claude Code 2.1.290 at the last invocation (same caveat), cairn 0.5.0 code, models seen: claude-sonnet-5-5

Statistics: 95% bootstrap intervals over tasks (each task's runs averaged first); paired
two-sided Wilcoxon signed-rank tests over tasks (exact for n <= 25). Each paired table reports
raw p and Holm-adjusted p (across its comparisons, per metric); a claim below is called
significant only when it survives that adjustment. Tied per-task differences (k/3 fractions)
are rounded before ranking. Cost is Claude Code's
reported API-equivalent cost; these runs were made on a subscription.

## Findings

**Significant after Holm adjustment (two results):**
1. **Haiku used 19% fewer fresh tokens with cairn's INDEX (C) than with no map**, over all 28
   tasks (-2,358 per task; p = 0.003, adjusted 0.022).
2. **Sonnet with the INDEX (C) cost 12% less per task than with the hand-written doc (B)**, over
   all 28 tasks ($0.0503 vs $0.0569; p = 0.005, adjusted 0.037).

**Consistent but not significant after adjustment:**
- Haiku cost per task with the INDEX: -25% vs no map (p = 0.037 raw, 0.22 adjusted).
- Sock Shop with Sonnet: every cairn condition was 24-26% cheaper than no map (raw p = 0.008-0.023,
  adjusted 0.055-0.12). Sock Shop is the **development set**: cairn's new link types were built on
  it, so this is not an independent test.
- Held-out Supabase with Sonnet: C/D/E 7-10% cheaper than no map (n.s.), and 19-22% cheaper than
  the hand-written doc (raw p = 0.031 for C and D, n.s. adjusted).

**Success rates did not change significantly.** Sonnet is at 99-100% in every condition.
Haiku rose from 86% (A) to 93% with the MCP server (E), but p = 0.15 before adjustment.

**Where cairn did worse (all not significant, reported because the spec requires it):**
- fleetline with Sonnet: C, D and E cost 7%, 10% and 10% *more* than no map.
- Supabase with Haiku: D cost 12% more than no map and succeeded 6 pp less.
- shopverse with Haiku: C, D and E used 1,400-2,200 *more* fresh tokens than the hand-written doc
  (raw p = 0.031, n.s. adjusted).

**The 0.5 detectors only change the map on Sock Shop.** On supabase-js, fleetline and shopverse
the 0.5 map is identical to 0.4's, so those results speak to cairn in general, not to the new
link types; the held-out evidence for the new link types is therefore limited.

**Correction to the first (2026-10-05) results.** That run reported Haiku reaching 100% with the
INDEX. It doesn't replicate: Haiku with C scored 92% on fleetline and 89% on shopverse, the same
as no map.

**What this means.** On this evidence cairn tends to make cross-repo work cheaper (fewer fresh
tokens for Haiku; cheaper than a hand-written doc for Sonnet), with the largest raw savings on a
real microservices workspace. It does not make these models measurably more accurate, the
effects vary by workspace and include some regressions, and 6-8 tasks per suite gives limited
power. A larger held-out suite is the next step.

Raw logs: `bench/results/lean/<model>/<suite>/*.jsonl` (local, not committed); reproduce with
`cairn bench` and `bench/combine_results.py`.

---

## Full tables

Conditions: A cold, B hand-written doc, C cairn INDEX, D INDEX + cards, E D + MCP

## All suites / haiku

| Condition | Runs | Success | Fresh tokens | Cache-read tokens | Cost (USD) | Turns | Errors |
|---|---|---|---|---|---|---|---|
| A | 84 | 86% | 12,347 | 222,206 | 0.0624 | 11.0 | 0 |
| B | 84 | 85% | 12,054 | 157,276 | 0.0499 | 8.1 | 0 |
| C | 84 | 87% | 9,989 | 131,150 | 0.0467 | 7.1 | 0 |
| D | 84 | 87% | 10,497 | 140,097 | 0.0491 | 7.7 | 0 |
| E | 84 | 93% | 11,386 | 171,194 | 0.0503 | 8.5 | 0 |

### Uncertainty

95% bootstrap intervals over tasks (each task's runs averaged first).

| Condition | Success | Cost per task (USD) | Fresh tokens |
|---|---|---|---|
| A (95% CI) | 86% [79%, 92%] | 0.0624 [0.0483, 0.0780] | 12,347 [9,748, 15,377] |
| B (95% CI) | 85% [73%, 94%] | 0.0499 [0.0379, 0.0645] | 12,054 [9,037, 15,666] |
| C (95% CI) | 87% [77%, 95%] | 0.0467 [0.0355, 0.0602] | 9,989 [8,088, 12,163] |
| D (95% CI) | 87% [75%, 96%] | 0.0491 [0.0361, 0.0678] | 10,497 [8,615, 12,644] |
| E (95% CI) | 93% [86%, 99%] | 0.0503 [0.0388, 0.0654] | 11,386 [8,893, 14,544] |

### Paired tests

Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks). p is unadjusted; p adj is Holm-adjusted across this table's comparisons, per metric.

| Comparison | Tasks | Success diff | p | p adj | Cost diff (USD) | p | p adj | Fresh-token diff | p | p adj |
|---|---|---|---|---|---|---|---|---|---|---|
| B vs A | 28 | -1 pp | 1.000 | 1.000 | -0.0125 | 0.020 | 0.137 | -294 | 0.561 | 1.000 |
| C vs A | 28 | +1 pp | 1.000 | 1.000 | -0.0157 | 0.037 | 0.223 | -2,358 | 0.003 | 0.022 |
| D vs A | 28 | +1 pp | 1.000 | 1.000 | -0.0133 | 0.078 | 0.388 | -1,850 | 0.039 | 0.236 |
| E vs A | 28 | +7 pp | 0.148 | 1.000 | -0.0121 | 0.183 | 0.731 | -961 | 0.161 | 0.646 |
| C vs B | 28 | +2 pp | 0.799 | 1.000 | -0.0032 | 0.531 | 1.000 | -2,064 | 0.086 | 0.428 |
| D vs B | 28 | +2 pp | 0.690 | 1.000 | -0.0008 | 0.811 | 1.000 | -1,556 | 0.393 | 1.000 |
| E vs B | 28 | +8 pp | 0.292 | 1.000 | +0.0004 | 0.446 | 1.000 | -667 | 0.955 | 1.000 |

### Break-even

Per-task cost against the cold baseline. One-time costs are not counted: cairn's scan is local (seconds, no tokens), but the synthetic suites ship pre-written repo summaries whose /cairn authoring tokens are not counted, nor is the time to write condition B's doc.

| Condition | Per task vs A |
|---|---|
| B break-even | saves $0.0125 per task (p = 0.020) (the doc's writing time is not counted) |
| C break-even | saves $0.0157 per task (p = 0.037) |
| D break-even | saves $0.0133 per task (p = 0.078, not significant) |
| E break-even | saves $0.0121 per task (p = 0.183, not significant) |

## All suites / sonnet

| Condition | Runs | Success | Fresh tokens | Cache-read tokens | Cost (USD) | Turns | Errors |
|---|---|---|---|---|---|---|---|
| A | 84 | 99% | 9,299 | 72,315 | 0.0573 | 4.6 | 0 |
| B | 84 | 99% | 9,499 | 64,693 | 0.0569 | 4.3 | 0 |
| C | 84 | 100% | 8,335 | 59,599 | 0.0503 | 3.7 | 0 |
| D | 84 | 100% | 8,688 | 58,111 | 0.0514 | 4.1 | 0 |
| E | 84 | 99% | 8,699 | 59,510 | 0.0515 | 3.7 | 0 |

### Uncertainty

95% bootstrap intervals over tasks (each task's runs averaged first).

| Condition | Success | Cost per task (USD) | Fresh tokens |
|---|---|---|---|
| A (95% CI) | 99% [96%, 100%] | 0.0573 [0.0474, 0.0680] | 9,299 [7,569, 11,199] |
| B (95% CI) | 99% [96%, 100%] | 0.0569 [0.0484, 0.0660] | 9,499 [7,986, 11,189] |
| C (95% CI) | 100% [100%, 100%] | 0.0503 [0.0444, 0.0567] | 8,335 [7,250, 9,598] |
| D (95% CI) | 100% [100%, 100%] | 0.0514 [0.0446, 0.0589] | 8,688 [7,488, 9,989] |
| E (95% CI) | 99% [96%, 100%] | 0.0515 [0.0453, 0.0582] | 8,699 [7,606, 9,842] |

### Paired tests

Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks). p is unadjusted; p adj is Holm-adjusted across this table's comparisons, per metric.

| Comparison | Tasks | Success diff | p | p adj | Cost diff (USD) | p | p adj | Fresh-token diff | p | p adj |
|---|---|---|---|---|---|---|---|---|---|---|
| B vs A | 28 | +0 pp | 1.000 | 1.000 | -0.0004 | 0.690 | 1.000 | +200 | 0.250 | 1.000 |
| C vs A | 28 | +1 pp | 1.000 | 1.000 | -0.0070 | 0.168 | 0.673 | -964 | 0.406 | 1.000 |
| D vs A | 28 | +1 pp | 1.000 | 1.000 | -0.0059 | 0.459 | 1.000 | -611 | 0.759 | 1.000 |
| E vs A | 28 | +0 pp | 1.000 | 1.000 | -0.0058 | 0.561 | 1.000 | -600 | 0.741 | 1.000 |
| C vs B | 28 | +1 pp | 1.000 | 1.000 | -0.0066 | 0.005 | 0.037 | -1,164 | 0.009 | 0.064 |
| D vs B | 28 | +1 pp | 1.000 | 1.000 | -0.0055 | 0.031 | 0.188 | -811 | 0.168 | 0.842 |
| E vs B | 28 | +0 pp | 1.000 | 1.000 | -0.0054 | 0.031 | 0.188 | -800 | 0.114 | 0.681 |

### Break-even

Per-task cost against the cold baseline. One-time costs are not counted: cairn's scan is local (seconds, no tokens), but the synthetic suites ship pre-written repo summaries whose /cairn authoring tokens are not counted, nor is the time to write condition B's doc.

| Condition | Per task vs A |
|---|---|
| B break-even | saves $0.0004 per task (p = 0.690, not significant) (the doc's writing time is not counted) |
| C break-even | saves $0.0070 per task (p = 0.168, not significant) |
| D break-even | saves $0.0059 per task (p = 0.459, not significant) |
| E break-even | saves $0.0058 per task (p = 0.561, not significant) |

## fleetline / haiku

| Condition | Runs | Success | Fresh tokens | Cache-read tokens | Cost (USD) | Turns | Errors |
|---|---|---|---|---|---|---|---|
| A | 24 | 92% | 8,335 | 154,690 | 0.0451 | 10.2 | 0 |
| B | 24 | 92% | 7,205 | 102,738 | 0.0371 | 6.3 | 0 |
| C | 24 | 92% | 6,138 | 79,571 | 0.0323 | 5.3 | 0 |
| D | 24 | 100% | 6,946 | 91,859 | 0.0399 | 6.1 | 0 |
| E | 24 | 96% | 6,781 | 101,839 | 0.0420 | 5.7 | 0 |

### Uncertainty

95% bootstrap intervals over tasks (each task's runs averaged first).

| Condition | Success | Cost per task (USD) | Fresh tokens |
|---|---|---|---|
| A (95% CI) | 92% [79%, 100%] | 0.0451 [0.0316, 0.0578] | 8,335 [6,488, 10,158] |
| B (95% CI) | 92% [79%, 100%] | 0.0371 [0.0240, 0.0537] | 7,205 [5,527, 9,021] |
| C (95% CI) | 92% [79%, 100%] | 0.0323 [0.0237, 0.0423] | 6,138 [5,243, 7,211] |
| D (95% CI) | 100% [100%, 100%] | 0.0399 [0.0263, 0.0543] | 6,946 [5,513, 8,412] |
| E (95% CI) | 96% [88%, 100%] | 0.0420 [0.0316, 0.0529] | 6,781 [5,581, 8,087] |

### Paired tests

Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks). p is unadjusted; p adj is Holm-adjusted across this table's comparisons, per metric.

| Comparison | Tasks | Success diff | p | p adj | Cost diff (USD) | p | p adj | Fresh-token diff | p | p adj |
|---|---|---|---|---|---|---|---|---|---|---|
| B vs A | 8 | +0 pp | 1.000 | 1.000 | -0.0080 | 0.312 | 1.000 | -1,130 | 0.461 | 1.000 |
| C vs A | 8 | +0 pp | 1.000 | 1.000 | -0.0128 | 0.148 | 1.000 | -2,198 | 0.055 | 0.383 |
| D vs A | 8 | +8 pp | 0.500 | 1.000 | -0.0052 | 0.312 | 1.000 | -1,390 | 0.312 | 1.000 |
| E vs A | 8 | +4 pp | 1.000 | 1.000 | -0.0031 | 0.742 | 1.000 | -1,554 | 0.250 | 1.000 |
| C vs B | 8 | +0 pp | 1.000 | 1.000 | -0.0048 | 0.383 | 1.000 | -1,068 | 0.250 | 1.000 |
| D vs B | 8 | +8 pp | 0.500 | 1.000 | +0.0028 | 0.742 | 1.000 | -260 | 1.000 | 1.000 |
| E vs B | 8 | +4 pp | 1.000 | 1.000 | +0.0049 | 0.312 | 1.000 | -424 | 0.641 | 1.000 |

### Break-even

Per-task cost against the cold baseline. One-time costs are not counted: cairn's scan is local (seconds, no tokens), but the synthetic suites ship pre-written repo summaries whose /cairn authoring tokens are not counted, nor is the time to write condition B's doc.

| Condition | Per task vs A |
|---|---|
| B break-even | saves $0.0080 per task (p = 0.312, not significant) (the doc's writing time is not counted) |
| C break-even | saves $0.0128 per task (p = 0.148, not significant) |
| D break-even | saves $0.0052 per task (p = 0.312, not significant) |
| E break-even | saves $0.0031 per task (p = 0.742, not significant) |

## shopverse / haiku

| Condition | Runs | Success | Fresh tokens | Cache-read tokens | Cost (USD) | Turns | Errors |
|---|---|---|---|---|---|---|---|
| A | 18 | 89% | 8,182 | 164,404 | 0.0506 | 10.6 | 0 |
| B | 18 | 83% | 5,744 | 63,870 | 0.0330 | 4.9 | 0 |
| C | 18 | 89% | 7,208 | 105,251 | 0.0289 | 7.0 | 0 |
| D | 18 | 89% | 7,954 | 119,030 | 0.0320 | 8.2 | 0 |
| E | 18 | 89% | 7,143 | 92,838 | 0.0326 | 6.4 | 0 |

### Uncertainty

95% bootstrap intervals over tasks (each task's runs averaged first).

| Condition | Success | Cost per task (USD) | Fresh tokens |
|---|---|---|---|
| A (95% CI) | 89% [78%, 100%] | 0.0506 [0.0272, 0.0753] | 8,182 [6,109, 11,287] |
| B (95% CI) | 83% [50%, 100%] | 0.0330 [0.0161, 0.0522] | 5,744 [4,358, 7,254] |
| C (95% CI) | 89% [67%, 100%] | 0.0289 [0.0213, 0.0388] | 7,208 [5,668, 9,148] |
| D (95% CI) | 89% [78%, 100%] | 0.0320 [0.0196, 0.0455] | 7,954 [5,494, 10,652] |
| E (95% CI) | 89% [67%, 100%] | 0.0326 [0.0180, 0.0515] | 7,143 [5,463, 9,035] |

### Paired tests

Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks). p is unadjusted; p adj is Holm-adjusted across this table's comparisons, per metric.

| Comparison | Tasks | Success diff | p | p adj | Cost diff (USD) | p | p adj | Fresh-token diff | p | p adj |
|---|---|---|---|---|---|---|---|---|---|---|
| B vs A | 6 | -6 pp | 1.000 | 1.000 | -0.0176 | 0.438 | 1.000 | -2,438 | 0.156 | 0.625 |
| C vs A | 6 | +0 pp | 1.000 | 1.000 | -0.0216 | 0.156 | 1.000 | -975 | 0.312 | 0.938 |
| D vs A | 6 | +0 pp | 1.000 | 1.000 | -0.0185 | 0.562 | 1.000 | -228 | 0.844 | 0.938 |
| E vs A | 6 | +0 pp | 1.000 | 1.000 | -0.0180 | 0.312 | 1.000 | -1,039 | 0.438 | 0.938 |
| C vs B | 6 | +6 pp | 1.000 | 1.000 | -0.0041 | 1.000 | 1.000 | +1,464 | 0.031 | 0.219 |
| D vs B | 6 | +6 pp | 1.000 | 1.000 | -0.0010 | 1.000 | 1.000 | +2,210 | 0.031 | 0.219 |
| E vs B | 6 | +6 pp | 1.000 | 1.000 | -0.0004 | 0.844 | 1.000 | +1,399 | 0.031 | 0.219 |

### Break-even

Per-task cost against the cold baseline. One-time costs are not counted: cairn's scan is local (seconds, no tokens), but the synthetic suites ship pre-written repo summaries whose /cairn authoring tokens are not counted, nor is the time to write condition B's doc.

| Condition | Per task vs A |
|---|---|
| B break-even | saves $0.0176 per task (p = 0.438, not significant) (the doc's writing time is not counted) |
| C break-even | saves $0.0216 per task (p = 0.156, not significant) |
| D break-even | saves $0.0185 per task (p = 0.562, not significant) |
| E break-even | saves $0.0180 per task (p = 0.312, not significant) |

## sockshop / haiku

| Condition | Runs | Success | Fresh tokens | Cache-read tokens | Cost (USD) | Turns | Errors |
|---|---|---|---|---|---|---|---|
| A | 24 | 83% | 15,552 | 286,913 | 0.0783 | 12.0 | 0 |
| B | 24 | 92% | 16,038 | 197,386 | 0.0578 | 9.1 | 0 |
| C | 24 | 83% | 11,643 | 127,783 | 0.0572 | 6.8 | 0 |
| D | 24 | 83% | 11,458 | 135,839 | 0.0439 | 7.1 | 0 |
| E | 24 | 92% | 13,721 | 173,118 | 0.0505 | 10.0 | 0 |

### Uncertainty

95% bootstrap intervals over tasks (each task's runs averaged first).

| Condition | Success | Cost per task (USD) | Fresh tokens |
|---|---|---|---|
| A (95% CI) | 83% [67%, 96%] | 0.0783 [0.0435, 0.1182] | 15,552 [10,189, 21,821] |
| B (95% CI) | 92% [75%, 100%] | 0.0578 [0.0356, 0.0863] | 16,038 [10,089, 24,063] |
| C (95% CI) | 83% [58%, 100%] | 0.0572 [0.0372, 0.0803] | 11,643 [8,393, 15,018] |
| D (95% CI) | 83% [58%, 100%] | 0.0439 [0.0340, 0.0561] | 11,458 [8,927, 14,423] |
| E (95% CI) | 92% [75%, 100%] | 0.0505 [0.0384, 0.0653] | 13,721 [10,597, 17,180] |

### Paired tests

Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks). p is unadjusted; p adj is Holm-adjusted across this table's comparisons, per metric.

| Comparison | Tasks | Success diff | p | p adj | Cost diff (USD) | p | p adj | Fresh-token diff | p | p adj |
|---|---|---|---|---|---|---|---|---|---|---|
| B vs A | 8 | +8 pp | 0.750 | 1.000 | -0.0204 | 0.109 | 0.766 | +486 | 0.945 | 1.000 |
| C vs A | 8 | +0 pp | 1.000 | 1.000 | -0.0211 | 0.945 | 1.000 | -3,909 | 0.250 | 1.000 |
| D vs A | 8 | +0 pp | 1.000 | 1.000 | -0.0344 | 0.312 | 1.000 | -4,094 | 0.148 | 0.742 |
| E vs A | 8 | +8 pp | 0.500 | 1.000 | -0.0278 | 0.383 | 1.000 | -1,831 | 0.383 | 1.000 |
| C vs B | 8 | -8 pp | 0.750 | 1.000 | -0.0006 | 1.000 | 1.000 | -4,395 | 0.078 | 0.469 |
| D vs B | 8 | -8 pp | 0.750 | 1.000 | -0.0140 | 0.461 | 1.000 | -4,580 | 0.055 | 0.383 |
| E vs B | 8 | +0 pp | 1.000 | 1.000 | -0.0074 | 0.844 | 1.000 | -2,317 | 0.945 | 1.000 |

### Break-even

Per-task cost against the cold baseline. One-time costs are not counted: cairn's scan is local (seconds, no tokens), but the synthetic suites ship pre-written repo summaries whose /cairn authoring tokens are not counted, nor is the time to write condition B's doc.

| Condition | Per task vs A |
|---|---|
| B break-even | saves $0.0204 per task (p = 0.109, not significant) (the doc's writing time is not counted) |
| C break-even | saves $0.0211 per task (p = 0.945, not significant) |
| D break-even | saves $0.0344 per task (p = 0.312, not significant) |
| E break-even | saves $0.0278 per task (p = 0.383, not significant) |

## supabase-js / haiku

| Condition | Runs | Success | Fresh tokens | Cache-read tokens | Cost (USD) | Turns | Errors |
|---|---|---|---|---|---|---|---|
| A | 18 | 78% | 17,588 | 283,756 | 0.0762 | 11.3 | 0 |
| B | 18 | 67% | 19,515 | 269,917 | 0.0735 | 12.4 | 0 |
| C | 18 | 83% | 15,701 | 230,312 | 0.0697 | 9.9 | 0 |
| D | 18 | 72% | 16,495 | 231,156 | 0.0856 | 10.3 | 0 |
| E | 18 | 94% | 18,657 | 339,459 | 0.0789 | 12.4 | 0 |

### Uncertainty

95% bootstrap intervals over tasks (each task's runs averaged first).

| Condition | Success | Cost per task (USD) | Fresh tokens |
|---|---|---|---|
| A (95% CI) | 78% [67%, 89%] | 0.0762 [0.0521, 0.1056] | 17,588 [11,557, 24,571] |
| B (95% CI) | 67% [44%, 89%] | 0.0735 [0.0463, 0.1143] | 19,515 [13,833, 27,965] |
| C (95% CI) | 83% [61%, 100%] | 0.0697 [0.0370, 0.1157] | 15,701 [10,714, 21,026] |
| D (95% CI) | 72% [39%, 100%] | 0.0856 [0.0411, 0.1600] | 16,495 [11,805, 21,865] |
| E (95% CI) | 94% [83%, 100%] | 0.0789 [0.0386, 0.1344] | 18,657 [10,846, 29,229] |

### Paired tests

Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks). p is unadjusted; p adj is Holm-adjusted across this table's comparisons, per metric.

| Comparison | Tasks | Success diff | p | p adj | Cost diff (USD) | p | p adj | Fresh-token diff | p | p adj |
|---|---|---|---|---|---|---|---|---|---|---|
| B vs A | 6 | -11 pp | 0.500 | 1.000 | -0.0027 | 0.844 | 1.000 | +1,926 | 0.312 | 1.000 |
| C vs A | 6 | +6 pp | 1.000 | 1.000 | -0.0064 | 0.562 | 1.000 | -1,888 | 0.219 | 1.000 |
| D vs A | 6 | -6 pp | 1.000 | 1.000 | +0.0094 | 0.688 | 1.000 | -1,094 | 0.562 | 1.000 |
| E vs A | 6 | +17 pp | 0.250 | 1.000 | +0.0028 | 0.844 | 1.000 | +1,069 | 0.844 | 1.000 |
| C vs B | 6 | +17 pp | 0.250 | 1.000 | -0.0037 | 0.562 | 1.000 | -3,814 | 0.156 | 1.000 |
| D vs B | 6 | +6 pp | 1.000 | 1.000 | +0.0121 | 1.000 | 1.000 | -3,020 | 0.219 | 1.000 |
| E vs B | 6 | +28 pp | 0.125 | 0.875 | +0.0055 | 0.688 | 1.000 | -858 | 0.688 | 1.000 |

### Break-even

Per-task cost against the cold baseline. One-time costs are not counted: cairn's scan is local (seconds, no tokens), but the synthetic suites ship pre-written repo summaries whose /cairn authoring tokens are not counted, nor is the time to write condition B's doc.

| Condition | Per task vs A |
|---|---|
| B break-even | saves $0.0027 per task (p = 0.844, not significant) (the doc's writing time is not counted) |
| C break-even | saves $0.0064 per task (p = 0.562, not significant) |
| D break-even | costs $0.0094 more per task (p = 0.688, not significant) |
| E break-even | costs $0.0028 more per task (p = 0.844, not significant) |

## fleetline / sonnet

| Condition | Runs | Success | Fresh tokens | Cache-read tokens | Cost (USD) | Turns | Errors |
|---|---|---|---|---|---|---|---|
| A | 24 | 100% | 7,253 | 60,298 | 0.0456 | 3.9 | 0 |
| B | 24 | 100% | 8,425 | 68,044 | 0.0536 | 4.8 | 0 |
| C | 24 | 100% | 7,540 | 67,734 | 0.0486 | 3.7 | 0 |
| D | 24 | 100% | 8,625 | 56,986 | 0.0504 | 3.8 | 0 |
| E | 24 | 100% | 8,315 | 61,241 | 0.0500 | 3.7 | 0 |

### Uncertainty

95% bootstrap intervals over tasks (each task's runs averaged first).

| Condition | Success | Cost per task (USD) | Fresh tokens |
|---|---|---|---|
| A (95% CI) | 100% [100%, 100%] | 0.0456 [0.0364, 0.0581] | 7,253 [5,705, 9,368] |
| B (95% CI) | 100% [100%, 100%] | 0.0536 [0.0449, 0.0665] | 8,425 [6,971, 10,509] |
| C (95% CI) | 100% [100%, 100%] | 0.0486 [0.0424, 0.0562] | 7,540 [6,586, 8,839] |
| D (95% CI) | 100% [100%, 100%] | 0.0504 [0.0407, 0.0643] | 8,625 [6,933, 10,921] |
| E (95% CI) | 100% [100%, 100%] | 0.0500 [0.0411, 0.0630] | 8,315 [6,916, 10,364] |

### Paired tests

Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks). p is unadjusted; p adj is Holm-adjusted across this table's comparisons, per metric.

| Comparison | Tasks | Success diff | p | p adj | Cost diff (USD) | p | p adj | Fresh-token diff | p | p adj |
|---|---|---|---|---|---|---|---|---|---|---|
| B vs A | 8 | +0 pp | 1.000 | 1.000 | +0.0080 | 0.023 | 0.164 | +1,172 | 0.055 | 0.383 |
| C vs A | 8 | +0 pp | 1.000 | 1.000 | +0.0030 | 0.547 | 1.000 | +287 | 0.742 | 1.000 |
| D vs A | 8 | +0 pp | 1.000 | 1.000 | +0.0048 | 0.148 | 0.742 | +1,372 | 0.055 | 0.383 |
| E vs A | 8 | +0 pp | 1.000 | 1.000 | +0.0044 | 0.078 | 0.469 | +1,062 | 0.055 | 0.383 |
| C vs B | 8 | +0 pp | 1.000 | 1.000 | -0.0050 | 0.195 | 0.781 | -885 | 0.109 | 0.438 |
| D vs B | 8 | +0 pp | 1.000 | 1.000 | -0.0032 | 0.742 | 1.000 | +200 | 0.742 | 1.000 |
| E vs B | 8 | +0 pp | 1.000 | 1.000 | -0.0036 | 0.312 | 0.938 | -110 | 0.844 | 1.000 |

### Break-even

Per-task cost against the cold baseline. One-time costs are not counted: cairn's scan is local (seconds, no tokens), but the synthetic suites ship pre-written repo summaries whose /cairn authoring tokens are not counted, nor is the time to write condition B's doc.

| Condition | Per task vs A |
|---|---|
| B break-even | costs $0.0080 more per task (p = 0.023) (the doc's writing time is not counted) |
| C break-even | costs $0.0030 more per task (p = 0.547, not significant) |
| D break-even | costs $0.0048 more per task (p = 0.148, not significant) |
| E break-even | costs $0.0044 more per task (p = 0.078, not significant) |

## shopverse / sonnet

| Condition | Runs | Success | Fresh tokens | Cache-read tokens | Cost (USD) | Turns | Errors |
|---|---|---|---|---|---|---|---|
| A | 18 | 94% | 8,162 | 66,168 | 0.0504 | 4.7 | 0 |
| B | 18 | 94% | 7,634 | 53,743 | 0.0459 | 4.0 | 0 |
| C | 18 | 100% | 6,988 | 58,440 | 0.0442 | 4.1 | 0 |
| D | 18 | 100% | 7,645 | 57,980 | 0.0467 | 4.3 | 0 |
| E | 18 | 94% | 7,714 | 58,352 | 0.0465 | 4.2 | 0 |

### Uncertainty

95% bootstrap intervals over tasks (each task's runs averaged first).

| Condition | Success | Cost per task (USD) | Fresh tokens |
|---|---|---|---|
| A (95% CI) | 94% [83%, 100%] | 0.0504 [0.0394, 0.0640] | 8,162 [5,928, 10,752] |
| B (95% CI) | 94% [83%, 100%] | 0.0459 [0.0320, 0.0618] | 7,634 [5,663, 10,073] |
| C (95% CI) | 100% [100%, 100%] | 0.0442 [0.0384, 0.0520] | 6,988 [6,189, 7,931] |
| D (95% CI) | 100% [100%, 100%] | 0.0467 [0.0354, 0.0626] | 7,645 [5,873, 10,124] |
| E (95% CI) | 94% [83%, 100%] | 0.0465 [0.0360, 0.0628] | 7,714 [6,041, 10,053] |

### Paired tests

Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks). p is unadjusted; p adj is Holm-adjusted across this table's comparisons, per metric.

| Comparison | Tasks | Success diff | p | p adj | Cost diff (USD) | p | p adj | Fresh-token diff | p | p adj |
|---|---|---|---|---|---|---|---|---|---|---|
| B vs A | 6 | +0 pp | 1.000 | 1.000 | -0.0046 | 0.688 | 1.000 | -528 | 1.000 | 1.000 |
| C vs A | 6 | +6 pp | 1.000 | 1.000 | -0.0062 | 0.438 | 1.000 | -1,174 | 1.000 | 1.000 |
| D vs A | 6 | +6 pp | 1.000 | 1.000 | -0.0038 | 1.000 | 1.000 | -517 | 1.000 | 1.000 |
| E vs A | 6 | +0 pp | 1.000 | 1.000 | -0.0039 | 1.000 | 1.000 | -448 | 0.844 | 1.000 |
| C vs B | 6 | +6 pp | 1.000 | 1.000 | -0.0017 | 0.688 | 1.000 | -646 | 0.844 | 1.000 |
| D vs B | 6 | +6 pp | 1.000 | 1.000 | +0.0008 | 1.000 | 1.000 | +11 | 1.000 | 1.000 |
| E vs B | 6 | +0 pp | 1.000 | 1.000 | +0.0007 | 1.000 | 1.000 | +81 | 1.000 | 1.000 |

### Break-even

Per-task cost against the cold baseline. One-time costs are not counted: cairn's scan is local (seconds, no tokens), but the synthetic suites ship pre-written repo summaries whose /cairn authoring tokens are not counted, nor is the time to write condition B's doc.

| Condition | Per task vs A |
|---|---|
| B break-even | saves $0.0046 per task (p = 0.688, not significant) (the doc's writing time is not counted) |
| C break-even | saves $0.0062 per task (p = 0.438, not significant) |
| D break-even | saves $0.0038 per task (p = 1.000, not significant) |
| E break-even | saves $0.0039 per task (p = 1.000, not significant) |

## sockshop / sonnet

| Condition | Runs | Success | Fresh tokens | Cache-read tokens | Cost (USD) | Turns | Errors |
|---|---|---|---|---|---|---|---|
| A | 24 | 100% | 12,475 | 93,477 | 0.0759 | 5.7 | 0 |
| B | 24 | 100% | 11,001 | 68,469 | 0.0637 | 4.2 | 0 |
| C | 24 | 100% | 9,935 | 57,132 | 0.0565 | 3.7 | 0 |
| D | 24 | 100% | 9,917 | 61,368 | 0.0576 | 4.5 | 0 |
| E | 24 | 100% | 10,057 | 57,086 | 0.0567 | 3.5 | 0 |

### Uncertainty

95% bootstrap intervals over tasks (each task's runs averaged first).

| Condition | Success | Cost per task (USD) | Fresh tokens |
|---|---|---|---|
| A (95% CI) | 100% [100%, 100%] | 0.0759 [0.0552, 0.0981] | 12,475 [8,962, 16,385] |
| B (95% CI) | 100% [100%, 100%] | 0.0637 [0.0494, 0.0789] | 11,001 [8,237, 14,056] |
| C (95% CI) | 100% [100%, 100%] | 0.0565 [0.0430, 0.0727] | 9,935 [7,327, 13,296] |
| D (95% CI) | 100% [100%, 100%] | 0.0576 [0.0435, 0.0747] | 9,917 [7,287, 13,036] |
| E (95% CI) | 100% [100%, 100%] | 0.0567 [0.0456, 0.0691] | 10,057 [7,847, 12,645] |

### Paired tests

Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks). p is unadjusted; p adj is Holm-adjusted across this table's comparisons, per metric.

| Comparison | Tasks | Success diff | p | p adj | Cost diff (USD) | p | p adj | Fresh-token diff | p | p adj |
|---|---|---|---|---|---|---|---|---|---|---|
| B vs A | 8 | +0 pp | 1.000 | 1.000 | -0.0122 | 0.023 | 0.117 | -1,474 | 0.109 | 0.438 |
| C vs A | 8 | +0 pp | 1.000 | 1.000 | -0.0194 | 0.008 | 0.055 | -2,540 | 0.023 | 0.141 |
| D vs A | 8 | +0 pp | 1.000 | 1.000 | -0.0183 | 0.023 | 0.117 | -2,558 | 0.016 | 0.109 |
| E vs A | 8 | +0 pp | 1.000 | 1.000 | -0.0192 | 0.016 | 0.094 | -2,418 | 0.023 | 0.141 |
| C vs B | 8 | +0 pp | 1.000 | 1.000 | -0.0072 | 0.109 | 0.328 | -1,066 | 0.195 | 0.586 |
| D vs B | 8 | +0 pp | 1.000 | 1.000 | -0.0061 | 0.195 | 0.328 | -1,084 | 0.250 | 0.586 |
| E vs B | 8 | +0 pp | 1.000 | 1.000 | -0.0070 | 0.109 | 0.328 | -944 | 0.312 | 0.586 |

### Break-even

Per-task cost against the cold baseline. One-time costs are not counted: cairn's scan is local (seconds, no tokens), but the synthetic suites ship pre-written repo summaries whose /cairn authoring tokens are not counted, nor is the time to write condition B's doc.

| Condition | Per task vs A |
|---|---|
| B break-even | saves $0.0122 per task (p = 0.023) (the doc's writing time is not counted) |
| C break-even | saves $0.0194 per task (p = 0.008) |
| D break-even | saves $0.0183 per task (p = 0.023) |
| E break-even | saves $0.0192 per task (p = 0.016) |

## supabase-js / sonnet

| Condition | Runs | Success | Fresh tokens | Cache-read tokens | Cost (USD) | Turns | Errors |
|---|---|---|---|---|---|---|---|
| A | 18 | 100% | 8,927 | 66,268 | 0.0550 | 3.9 | 0 |
| B | 18 | 100% | 10,794 | 66,139 | 0.0633 | 4.2 | 0 |
| C | 18 | 100% | 8,608 | 53,200 | 0.0503 | 3.3 | 0 |
| D | 18 | 100% | 8,176 | 55,401 | 0.0493 | 3.6 | 0 |
| E | 18 | 100% | 8,385 | 61,590 | 0.0513 | 3.7 | 0 |

### Uncertainty

95% bootstrap intervals over tasks (each task's runs averaged first).

| Condition | Success | Cost per task (USD) | Fresh tokens |
|---|---|---|---|
| A (95% CI) | 100% [100%, 100%] | 0.0550 [0.0351, 0.0847] | 8,927 [5,611, 14,284] |
| B (95% CI) | 100% [100%, 100%] | 0.0633 [0.0403, 0.0932] | 10,794 [6,853, 16,360] |
| C (95% CI) | 100% [100%, 100%] | 0.0503 [0.0360, 0.0668] | 8,608 [6,195, 11,368] |
| D (95% CI) | 100% [100%, 100%] | 0.0493 [0.0369, 0.0631] | 8,176 [6,193, 10,491] |
| E (95% CI) | 100% [100%, 100%] | 0.0513 [0.0391, 0.0662] | 8,385 [6,472, 10,790] |

### Paired tests

Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks). p is unadjusted; p adj is Holm-adjusted across this table's comparisons, per metric.

| Comparison | Tasks | Success diff | p | p adj | Cost diff (USD) | p | p adj | Fresh-token diff | p | p adj |
|---|---|---|---|---|---|---|---|---|---|---|
| B vs A | 6 | +0 pp | 1.000 | 1.000 | +0.0083 | 0.031 | 0.219 | +1,867 | 0.031 | 0.219 |
| C vs A | 6 | +0 pp | 1.000 | 1.000 | -0.0047 | 0.844 | 1.000 | -319 | 0.438 | 1.000 |
| D vs A | 6 | +0 pp | 1.000 | 1.000 | -0.0057 | 0.562 | 1.000 | -752 | 0.438 | 1.000 |
| E vs A | 6 | +0 pp | 1.000 | 1.000 | -0.0037 | 0.562 | 1.000 | -542 | 0.438 | 1.000 |
| C vs B | 6 | +0 pp | 1.000 | 1.000 | -0.0129 | 0.031 | 0.219 | -2,186 | 0.062 | 0.312 |
| D vs B | 6 | +0 pp | 1.000 | 1.000 | -0.0139 | 0.031 | 0.219 | -2,618 | 0.031 | 0.219 |
| E vs B | 6 | +0 pp | 1.000 | 1.000 | -0.0119 | 0.156 | 0.625 | -2,408 | 0.094 | 0.375 |

### Break-even

Per-task cost against the cold baseline. One-time costs are not counted: cairn's scan is local (seconds, no tokens), but the synthetic suites ship pre-written repo summaries whose /cairn authoring tokens are not counted, nor is the time to write condition B's doc.

| Condition | Per task vs A |
|---|---|
| B break-even | costs $0.0083 more per task (p = 0.031) (the doc's writing time is not counted) |
| C break-even | saves $0.0047 per task (p = 0.844, not significant) |
| D break-even | saves $0.0057 per task (p = 0.562, not significant) |
| E break-even | saves $0.0037 per task (p = 0.562, not significant) |
