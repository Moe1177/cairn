# Agent benchmark: does the grep-first `query` help agents? (2026-10-06)

Plan B4 (lean): the 16 localization and impact tasks from sockshop, supabase-js, fleetline and
shopverse. Three conditions: **A** no map, **D** INDEX + cards, and **E** D + cairn's MCP server,
whose `query` now locates grep-first (see
[2026-10-06-locate.md](2026-10-06-locate.md)). Haiku 4.5 and Sonnet 5.5, 3 runs per cell, 288
runs, Claude Code headless with read-only tools. Cost is Claude Code's reported API-equivalent
cost; the runs were made on a subscription.

## Findings

**Nothing is significant after Holm adjustment.**

- **E (with `query`) did no better than D (INDEX + cards) for either model.** Paired over 16
  tasks:

  | Model | Success | Cost per task | Fresh tokens | Turns |
  |---|---|---|---|---|
  | Haiku | +4 pp (p = 0.63) | -$0.0004 (p = 0.90) | +1,170 (p = 0.13) | +2.4 (p = 0.10; adj 0.38) |
  | Sonnet | +0 pp | -$0.0001 (p = 0.50) | -30 (p = 0.30) | +0.1 (p = 0.84) |

  Haiku took about two more turns with the MCP server, a direction worth watching but not
  significant.
- **Against no map (A), both cairn conditions point the right way but are not significant:**
  - Haiku: success +8 pp with D and +12 pp with E;
  - Sonnet: success +6 pp, and cost -6%.
- **Why `query` didn't help is not known.** These runs don't record which tools an agent called
  (`--output-format json`), so it is unknown whether agents used `query` at all, or used it and
  gained nothing over their own grep. Recording tool calls is the next harness change before any
  rerun.

What this means for cairn: the offline benchmark showed grep-first locating beats the code
graph; this run shows the tool doesn't yet turn into fewer turns or tokens for real agents, who
already grep well. cairn's measured value remains the map (which repo to open), not finding the
line inside it.

## Combined report

# cairn benchmark (combined)

Conditions: A cold, B hand-written doc, C cairn INDEX, D INDEX + cards, E D + MCP

## All suites / haiku

| Condition | Runs | Success | Fresh tokens | Cache-read tokens | Cost (USD) | Turns | Errors |
|---|---|---|---|---|---|---|---|
| A | 48 | 81% | 13,736 | 261,268 | 0.0630 | 13.3 | 0 |
| D | 48 | 90% | 12,720 | 156,754 | 0.0603 | 9.5 | 0 |
| E | 48 | 94% | 13,890 | 211,926 | 0.0598 | 11.9 | 0 |

### Uncertainty

95% bootstrap intervals over tasks (each task's runs averaged first).

| Condition | Success | Cost per task (USD) | Fresh tokens |
|---|---|---|---|
| A (95% CI) | 81% [67%, 94%] | 0.0630 [0.0451, 0.0841] | 13,736 [9,970, 18,183] |
| D (95% CI) | 90% [75%, 100%] | 0.0603 [0.0417, 0.0850] | 12,720 [9,361, 16,698] |
| E (95% CI) | 94% [83%, 100%] | 0.0598 [0.0436, 0.0819] | 13,890 [10,409, 18,863] |

### Paired tests

Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks). p is unadjusted; p adj is Holm-adjusted across this table's comparisons, per metric.

| Comparison | Tasks | Success diff | p | p adj | Cost diff (USD) | p | p adj | Fresh-token diff | p | p adj |
|---|---|---|---|---|---|---|---|---|---|---|
| D vs A | 16 | +8 pp | 0.312 | 0.312 | -0.0027 | 0.744 | 1.000 | -1,016 | 0.144 | 0.288 |
| E vs A | 16 | +12 pp | 0.109 | 0.219 | -0.0032 | 0.821 | 1.000 | +154 | 0.900 | 0.900 |

### Break-even

Per-task cost against the cold baseline. One-time costs are not counted: cairn's scan is local (seconds, no tokens), but the synthetic suites ship pre-written repo summaries whose /cairn authoring tokens are not counted, nor is the time to write condition B's doc.

| Condition | Per task vs A |
|---|---|
| D break-even | saves $0.0027 per task (p = 0.744, not significant) |
| E break-even | saves $0.0032 per task (p = 0.821, not significant) |

## All suites / sonnet

| Condition | Runs | Success | Fresh tokens | Cache-read tokens | Cost (USD) | Turns | Errors |
|---|---|---|---|---|---|---|---|
| A | 48 | 94% | 10,104 | 74,654 | 0.0623 | 5.1 | 0 |
| D | 48 | 100% | 9,894 | 64,320 | 0.0586 | 4.3 | 0 |
| E | 48 | 100% | 9,863 | 64,533 | 0.0585 | 4.4 | 0 |

### Uncertainty

95% bootstrap intervals over tasks (each task's runs averaged first).

| Condition | Success | Cost per task (USD) | Fresh tokens |
|---|---|---|---|
| A (95% CI) | 94% [83%, 100%] | 0.0623 [0.0478, 0.0800] | 10,104 [7,500, 13,358] |
| D (95% CI) | 100% [100%, 100%] | 0.0586 [0.0505, 0.0675] | 9,894 [8,543, 11,408] |
| E (95% CI) | 100% [100%, 100%] | 0.0585 [0.0501, 0.0684] | 9,863 [8,373, 11,639] |

### Paired tests

Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks). p is unadjusted; p adj is Holm-adjusted across this table's comparisons, per metric.

| Comparison | Tasks | Success diff | p | p adj | Cost diff (USD) | p | p adj | Fresh-token diff | p | p adj |
|---|---|---|---|---|---|---|---|---|---|---|
| D vs A | 16 | +6 pp | 0.500 | 1.000 | -0.0037 | 0.632 | 1.000 | -211 | 0.175 | 0.351 |
| E vs A | 16 | +6 pp | 0.500 | 1.000 | -0.0038 | 0.900 | 1.000 | -241 | 0.404 | 0.404 |

### Break-even

Per-task cost against the cold baseline. One-time costs are not counted: cairn's scan is local (seconds, no tokens), but the synthetic suites ship pre-written repo summaries whose /cairn authoring tokens are not counted, nor is the time to write condition B's doc.

| Condition | Per task vs A |
|---|---|
| D break-even | saves $0.0037 per task (p = 0.632, not significant) |
| E break-even | saves $0.0038 per task (p = 0.900, not significant) |

## fleetline / haiku

| Condition | Runs | Success | Fresh tokens | Cache-read tokens | Cost (USD) | Turns | Errors |
|---|---|---|---|---|---|---|---|
| A | 15 | 100% | 9,426 | 148,344 | 0.0392 | 10.1 | 0 |
| D | 15 | 100% | 7,351 | 82,343 | 0.0343 | 6.3 | 0 |
| E | 15 | 100% | 9,934 | 151,456 | 0.0407 | 11.3 | 0 |

### Uncertainty

95% bootstrap intervals over tasks (each task's runs averaged first).

| Condition | Success | Cost per task (USD) | Fresh tokens |
|---|---|---|---|
| A (95% CI) | 100% [100%, 100%] | 0.0392 [0.0272, 0.0564] | 9,426 [6,940, 13,314] |
| D (95% CI) | 100% [100%, 100%] | 0.0343 [0.0250, 0.0463] | 7,351 [5,703, 9,268] |
| E (95% CI) | 100% [100%, 100%] | 0.0407 [0.0308, 0.0539] | 9,934 [8,063, 12,394] |

### Paired tests

Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks). p is unadjusted; p adj is Holm-adjusted across this table's comparisons, per metric.

| Comparison | Tasks | Success diff | p | p adj | Cost diff (USD) | p | p adj | Fresh-token diff | p | p adj |
|---|---|---|---|---|---|---|---|---|---|---|
| D vs A | 5 | +0 pp | 1.000 | 1.000 | -0.0049 | 0.625 | 1.000 | -2,075 | 0.062 | 0.125 |
| E vs A | 5 | +0 pp | 1.000 | 1.000 | +0.0016 | 0.812 | 1.000 | +508 | 0.438 | 0.438 |

### Break-even

Per-task cost against the cold baseline. One-time costs are not counted: cairn's scan is local (seconds, no tokens), but the synthetic suites ship pre-written repo summaries whose /cairn authoring tokens are not counted, nor is the time to write condition B's doc.

| Condition | Per task vs A |
|---|---|
| D break-even | saves $0.0049 per task (p = 0.625, not significant) |
| E break-even | costs $0.0016 more per task (p = 0.812, not significant) |

## shopverse / haiku

| Condition | Runs | Success | Fresh tokens | Cache-read tokens | Cost (USD) | Turns | Errors |
|---|---|---|---|---|---|---|---|
| A | 9 | 89% | 8,805 | 201,940 | 0.0561 | 12.6 | 0 |
| D | 9 | 100% | 9,406 | 141,746 | 0.0524 | 12.3 | 0 |
| E | 9 | 100% | 10,840 | 209,823 | 0.0498 | 14.2 | 0 |

### Uncertainty

95% bootstrap intervals over tasks (each task's runs averaged first).

| Condition | Success | Cost per task (USD) | Fresh tokens |
|---|---|---|---|
| A (95% CI) | 89% [67%, 100%] | 0.0561 [0.0442, 0.0794] | 8,805 [7,654, 9,935] |
| D (95% CI) | 100% [100%, 100%] | 0.0524 [0.0405, 0.0637] | 9,406 [6,122, 12,048] |
| E (95% CI) | 100% [100%, 100%] | 0.0498 [0.0381, 0.0603] | 10,840 [8,147, 13,281] |

### Paired tests

Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks). p is unadjusted; p adj is Holm-adjusted across this table's comparisons, per metric.

| Comparison | Tasks | Success diff | p | p adj | Cost diff (USD) | p | p adj | Fresh-token diff | p | p adj |
|---|---|---|---|---|---|---|---|---|---|---|
| D vs A | 3 | +11 pp | 1.000 | 1.000 | -0.0037 | 0.750 | 1.000 | +601 | 0.750 | 1.000 |
| E vs A | 3 | +11 pp | 1.000 | 1.000 | -0.0063 | 0.750 | 1.000 | +2,035 | 0.500 | 1.000 |

### Break-even

Per-task cost against the cold baseline. One-time costs are not counted: cairn's scan is local (seconds, no tokens), but the synthetic suites ship pre-written repo summaries whose /cairn authoring tokens are not counted, nor is the time to write condition B's doc.

| Condition | Per task vs A |
|---|---|
| D break-even | saves $0.0037 per task (p = 0.750, not significant) |
| E break-even | saves $0.0063 per task (p = 0.750, not significant) |

## sockshop / haiku

| Condition | Runs | Success | Fresh tokens | Cache-read tokens | Cost (USD) | Turns | Errors |
|---|---|---|---|---|---|---|---|
| A | 12 | 83% | 14,527 | 267,878 | 0.0627 | 13.4 | 0 |
| D | 12 | 100% | 14,927 | 136,482 | 0.0643 | 9.2 | 0 |
| E | 12 | 92% | 13,898 | 169,137 | 0.0678 | 10.0 | 0 |

### Uncertainty

95% bootstrap intervals over tasks (each task's runs averaged first).

| Condition | Success | Cost per task (USD) | Fresh tokens |
|---|---|---|---|
| A (95% CI) | 83% [67%, 100%] | 0.0627 [0.0351, 0.0904] | 14,527 [8,590, 20,464] |
| D (95% CI) | 100% [100%, 100%] | 0.0643 [0.0339, 0.0948] | 14,927 [9,663, 21,845] |
| E (95% CI) | 92% [75%, 100%] | 0.0678 [0.0448, 0.0909] | 13,898 [11,731, 17,223] |

### Paired tests

Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks). p is unadjusted; p adj is Holm-adjusted across this table's comparisons, per metric.

| Comparison | Tasks | Success diff | p | p adj | Cost diff (USD) | p | p adj | Fresh-token diff | p | p adj |
|---|---|---|---|---|---|---|---|---|---|---|
| D vs A | 4 | +17 pp | 0.500 | 1.000 | +0.0016 | 1.000 | 1.000 | +400 | 1.000 | 1.000 |
| E vs A | 4 | +8 pp | 1.000 | 1.000 | +0.0051 | 0.375 | 0.750 | -629 | 1.000 | 1.000 |

### Break-even

Per-task cost against the cold baseline. One-time costs are not counted: cairn's scan is local (seconds, no tokens), but the synthetic suites ship pre-written repo summaries whose /cairn authoring tokens are not counted, nor is the time to write condition B's doc.

| Condition | Per task vs A |
|---|---|
| D break-even | costs $0.0016 more per task (p = 1.000, not significant) |
| E break-even | costs $0.0051 more per task (p = 0.375, not significant) |

## supabase-js / haiku

| Condition | Runs | Success | Fresh tokens | Cache-read tokens | Cost (USD) | Turns | Errors |
|---|---|---|---|---|---|---|---|
| A | 12 | 50% | 22,029 | 440,312 | 0.0982 | 17.8 | 0 |
| D | 12 | 58% | 19,711 | 281,295 | 0.0946 | 11.4 | 0 |
| E | 12 | 83% | 21,114 | 331,880 | 0.0833 | 12.8 | 0 |

### Uncertainty

95% bootstrap intervals over tasks (each task's runs averaged first).

| Condition | Success | Cost per task (USD) | Fresh tokens |
|---|---|---|---|
| A (95% CI) | 50% [17%, 83%] | 0.0982 [0.0426, 0.1538] | 22,029 [11,279, 32,779] |
| D (95% CI) | 58% [17%, 92%] | 0.0946 [0.0404, 0.1711] | 19,711 [10,587, 28,834] |
| E (95% CI) | 83% [50%, 100%] | 0.0833 [0.0304, 0.1507] | 21,114 [8,722, 35,958] |

### Paired tests

Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks). p is unadjusted; p adj is Holm-adjusted across this table's comparisons, per metric.

| Comparison | Tasks | Success diff | p | p adj | Cost diff (USD) | p | p adj | Fresh-token diff | p | p adj |
|---|---|---|---|---|---|---|---|---|---|---|
| D vs A | 4 | +8 pp | 1.000 | 1.000 | -0.0036 | 1.000 | 1.000 | -2,318 | 0.250 | 0.500 |
| E vs A | 4 | +33 pp | 0.250 | 0.500 | -0.0149 | 0.625 | 1.000 | -915 | 0.875 | 0.875 |

### Break-even

Per-task cost against the cold baseline. One-time costs are not counted: cairn's scan is local (seconds, no tokens), but the synthetic suites ship pre-written repo summaries whose /cairn authoring tokens are not counted, nor is the time to write condition B's doc.

| Condition | Per task vs A |
|---|---|
| D break-even | saves $0.0036 per task (p = 1.000, not significant) |
| E break-even | saves $0.0149 per task (p = 0.625, not significant) |

## fleetline / sonnet

| Condition | Runs | Success | Fresh tokens | Cache-read tokens | Cost (USD) | Turns | Errors |
|---|---|---|---|---|---|---|---|
| A | 15 | 100% | 7,546 | 60,352 | 0.0478 | 3.9 | 0 |
| D | 15 | 100% | 9,279 | 55,342 | 0.0534 | 3.4 | 0 |
| E | 15 | 100% | 8,985 | 60,286 | 0.0535 | 3.7 | 0 |

### Uncertainty

95% bootstrap intervals over tasks (each task's runs averaged first).

| Condition | Success | Cost per task (USD) | Fresh tokens |
|---|---|---|---|
| A (95% CI) | 100% [100%, 100%] | 0.0478 [0.0374, 0.0684] | 7,546 [5,776, 10,777] |
| D (95% CI) | 100% [100%, 100%] | 0.0534 [0.0452, 0.0658] | 9,279 [7,790, 11,165] |
| E (95% CI) | 100% [100%, 100%] | 0.0535 [0.0455, 0.0652] | 8,985 [7,688, 10,773] |

### Paired tests

Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks). p is unadjusted; p adj is Holm-adjusted across this table's comparisons, per metric.

| Comparison | Tasks | Success diff | p | p adj | Cost diff (USD) | p | p adj | Fresh-token diff | p | p adj |
|---|---|---|---|---|---|---|---|---|---|---|
| D vs A | 5 | +0 pp | 1.000 | 1.000 | +0.0056 | 0.312 | 0.625 | +1,733 | 0.188 | 0.250 |
| E vs A | 5 | +0 pp | 1.000 | 1.000 | +0.0057 | 0.438 | 0.625 | +1,438 | 0.125 | 0.250 |

### Break-even

Per-task cost against the cold baseline. One-time costs are not counted: cairn's scan is local (seconds, no tokens), but the synthetic suites ship pre-written repo summaries whose /cairn authoring tokens are not counted, nor is the time to write condition B's doc.

| Condition | Per task vs A |
|---|---|
| D break-even | costs $0.0056 more per task (p = 0.312, not significant) |
| E break-even | costs $0.0057 more per task (p = 0.438, not significant) |

## shopverse / sonnet

| Condition | Runs | Success | Fresh tokens | Cache-read tokens | Cost (USD) | Turns | Errors |
|---|---|---|---|---|---|---|---|
| A | 9 | 89% | 9,330 | 69,569 | 0.0575 | 5.6 | 0 |
| D | 9 | 100% | 9,950 | 73,272 | 0.0612 | 6.3 | 0 |
| E | 9 | 100% | 9,337 | 70,660 | 0.0577 | 5.8 | 0 |

### Uncertainty

95% bootstrap intervals over tasks (each task's runs averaged first).

| Condition | Success | Cost per task (USD) | Fresh tokens |
|---|---|---|---|
| A (95% CI) | 89% [67%, 100%] | 0.0575 [0.0403, 0.0795] | 9,330 [6,017, 13,203] |
| D (95% CI) | 100% [100%, 100%] | 0.0612 [0.0436, 0.0891] | 9,950 [6,823, 14,482] |
| E (95% CI) | 100% [100%, 100%] | 0.0577 [0.0432, 0.0840] | 9,337 [6,841, 13,278] |

### Paired tests

Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks). p is unadjusted; p adj is Holm-adjusted across this table's comparisons, per metric.

| Comparison | Tasks | Success diff | p | p adj | Cost diff (USD) | p | p adj | Fresh-token diff | p | p adj |
|---|---|---|---|---|---|---|---|---|---|---|
| D vs A | 3 | +11 pp | 1.000 | 1.000 | +0.0036 | 0.500 | 1.000 | +620 | 0.500 | 1.000 |
| E vs A | 3 | +11 pp | 1.000 | 1.000 | +0.0001 | 1.000 | 1.000 | +7 | 1.000 | 1.000 |

### Break-even

Per-task cost against the cold baseline. One-time costs are not counted: cairn's scan is local (seconds, no tokens), but the synthetic suites ship pre-written repo summaries whose /cairn authoring tokens are not counted, nor is the time to write condition B's doc.

| Condition | Per task vs A |
|---|---|
| D break-even | costs $0.0036 more per task (p = 0.500, not significant) |
| E break-even | costs $0.0001 more per task (p = 1.000, not significant) |

## sockshop / sonnet

| Condition | Runs | Success | Fresh tokens | Cache-read tokens | Cost (USD) | Turns | Errors |
|---|---|---|---|---|---|---|---|
| A | 12 | 83% | 12,657 | 98,396 | 0.0790 | 6.4 | 0 |
| D | 12 | 100% | 10,872 | 71,273 | 0.0643 | 4.4 | 0 |
| E | 12 | 100% | 11,908 | 70,434 | 0.0684 | 4.5 | 0 |

### Uncertainty

95% bootstrap intervals over tasks (each task's runs averaged first).

| Condition | Success | Cost per task (USD) | Fresh tokens |
|---|---|---|---|
| A (95% CI) | 83% [50%, 100%] | 0.0790 [0.0550, 0.1209] | 12,657 [8,085, 20,798] |
| D (95% CI) | 100% [100%, 100%] | 0.0643 [0.0509, 0.0778] | 10,872 [8,492, 13,252] |
| E (95% CI) | 100% [100%, 100%] | 0.0684 [0.0511, 0.0908] | 11,908 [8,347, 16,048] |

### Paired tests

Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks). p is unadjusted; p adj is Holm-adjusted across this table's comparisons, per metric.

| Comparison | Tasks | Success diff | p | p adj | Cost diff (USD) | p | p adj | Fresh-token diff | p | p adj |
|---|---|---|---|---|---|---|---|---|---|---|
| D vs A | 4 | +17 pp | 1.000 | 1.000 | -0.0147 | 0.625 | 1.000 | -1,785 | 0.875 | 1.000 |
| E vs A | 4 | +17 pp | 1.000 | 1.000 | -0.0106 | 0.625 | 1.000 | -749 | 1.000 | 1.000 |

### Break-even

Per-task cost against the cold baseline. One-time costs are not counted: cairn's scan is local (seconds, no tokens), but the synthetic suites ship pre-written repo summaries whose /cairn authoring tokens are not counted, nor is the time to write condition B's doc.

| Condition | Per task vs A |
|---|---|
| D break-even | saves $0.0147 per task (p = 0.625, not significant) |
| E break-even | saves $0.0106 per task (p = 0.625, not significant) |

## supabase-js / sonnet

| Condition | Runs | Success | Fresh tokens | Cache-read tokens | Cost (USD) | Turns | Errors |
|---|---|---|---|---|---|---|---|
| A | 12 | 100% | 11,329 | 72,606 | 0.0673 | 4.9 | 0 |
| D | 12 | 100% | 9,641 | 61,876 | 0.0574 | 3.7 | 0 |
| E | 12 | 100% | 9,312 | 59,346 | 0.0555 | 3.9 | 0 |

### Uncertainty

95% bootstrap intervals over tasks (each task's runs averaged first).

| Condition | Success | Cost per task (USD) | Fresh tokens |
|---|---|---|---|
| A (95% CI) | 100% [100%, 100%] | 0.0673 [0.0376, 0.1157] | 11,329 [6,128, 20,255] |
| D (95% CI) | 100% [100%, 100%] | 0.0574 [0.0410, 0.0810] | 9,641 [6,814, 13,867] |
| E (95% CI) | 100% [100%, 100%] | 0.0555 [0.0389, 0.0759] | 9,312 [6,683, 13,222] |

### Paired tests

Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks). p is unadjusted; p adj is Holm-adjusted across this table's comparisons, per metric.

| Comparison | Tasks | Success diff | p | p adj | Cost diff (USD) | p | p adj | Fresh-token diff | p | p adj |
|---|---|---|---|---|---|---|---|---|---|---|
| D vs A | 4 | +0 pp | 1.000 | 1.000 | -0.0099 | 0.875 | 1.000 | -1,689 | 0.875 | 1.000 |
| E vs A | 4 | +0 pp | 1.000 | 1.000 | -0.0118 | 1.000 | 1.000 | -2,018 | 0.875 | 1.000 |

### Break-even

Per-task cost against the cold baseline. One-time costs are not counted: cairn's scan is local (seconds, no tokens), but the synthetic suites ship pre-written repo summaries whose /cairn authoring tokens are not counted, nor is the time to write condition B's doc.

| Condition | Per task vs A |
|---|---|
| D break-even | saves $0.0099 per task (p = 0.875, not significant) |
| E break-even | saves $0.0118 per task (p = 1.000, not significant) |
