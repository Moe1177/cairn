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
- `--model haiku`: Claude Code 2.1.290, cairn 0.5.0 code (its version string still read 0.4.0), models seen: claude-haiku-4-5-20251001
- `--model sonnet`: Claude Code 2.1.290, cairn 0.5.0 code (its version string still read 0.4.0), models seen: claude-sonnet-5-5

Statistics: 95% bootstrap intervals over tasks (each task's runs averaged first); paired
two-sided Wilcoxon signed-rank tests over tasks (exact for n <= 25). Cost is Claude Code's
reported API-equivalent cost; these runs were made on a subscription.

## Findings

1. **cairn cuts cost and tokens; the clearest effects are on the weaker model.** Haiku over all
   28 tasks: the INDEX alone (C) cost **25% less per task** than no map ($0.047 vs $0.062,
   p = 0.037) and used **19% fewer fresh tokens** (p = 0.003); INDEX + cards (D) used 15% fewer
   tokens (p = 0.039).
2. **On the real microservices workspace (Sock Shop), Sonnet saved 24-26% per task with every
   cairn condition**, all significant (p = 0.008-0.023 over 8 tasks). Haiku saved up to 44% there
   (D), but with 8 tasks that isn't significant.
3. **Against the hand-written doc (B), cairn is cheaper for Sonnet**: C, D and E cost 10-12% less
   per task than B (p = 0.005-0.031). For Haiku, cairn and the doc save similar amounts.
4. **Success rates barely move.** Sonnet is at 99-100% in every condition (a ceiling). Haiku goes
   from 86% (A) to 93% with the MCP server (E), but that isn't significant (p = 0.15).
5. **On the held-out suite (supabase-js) the effects are small and not significant**: Sonnet
   -7% to -10% cost with C/D/E; Haiku +17 pp success with E but -6 pp with D. Six tasks is too
   few to say more. The hand-written doc made Sonnet *more* expensive there (+15%, p = 0.031).
6. **Correction to the first (2026-10-05) results.** That run reported Haiku reaching 100% with
   the INDEX. With 840 runs it doesn't replicate: Haiku with C scores 92% on fleetline and 89% on
   shopverse, the same as with no map. The earlier claim came from too few runs.

What this means: cairn reliably makes an agent's cross-repo work cheaper, most of all on real
service-to-service architectures and with smaller models. It doesn't, on this evidence, make a
strong model more accurate: Sonnet already answers these tasks without help.

Raw logs: `bench/results/lean/<model>/<suite>/*.jsonl` in the repository's local results (not
committed); reproduce with `cairn bench` and `bench/combine_results.py`.

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

Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks).

| Comparison | Tasks | Success diff | p | Cost diff (USD) | p | Fresh-token diff | p |
|---|---|---|---|---|---|---|---|
| B vs A | 28 | -1 pp | 0.621 | -0.0125 | 0.020 | -294 | 0.561 |
| C vs A | 28 | +1 pp | 0.444 | -0.0157 | 0.037 | -2,358 | 0.003 |
| D vs A | 28 | +1 pp | 0.357 | -0.0133 | 0.078 | -1,850 | 0.039 |
| E vs A | 28 | +7 pp | 0.148 | -0.0121 | 0.183 | -961 | 0.161 |
| C vs B | 28 | +2 pp | 0.832 | -0.0032 | 0.531 | -2,064 | 0.086 |
| D vs B | 28 | +2 pp | 0.539 | -0.0008 | 0.811 | -1,556 | 0.393 |
| E vs B | 28 | +8 pp | 0.307 | +0.0004 | 0.446 | -667 | 0.955 |

### Break-even

cairn's setup is a local scan: no tokens. Per-task cost against the cold baseline:

| Condition | Per task vs A |
|---|---|
| B break-even | saves $0.0125: pays for itself from the first task |
| C break-even | saves $0.0157: pays for itself from the first task |
| D break-even | saves $0.0133: pays for itself from the first task |
| E break-even | saves $0.0121: pays for itself from the first task |

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

Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks).

| Comparison | Tasks | Success diff | p | Cost diff (USD) | p | Fresh-token diff | p |
|---|---|---|---|---|---|---|---|
| B vs A | 28 | +0 pp | 1.000 | -0.0004 | 0.690 | +200 | 0.250 |
| C vs A | 28 | +1 pp | 1.000 | -0.0070 | 0.168 | -964 | 0.406 |
| D vs A | 28 | +1 pp | 1.000 | -0.0059 | 0.459 | -611 | 0.759 |
| E vs A | 28 | +0 pp | 1.000 | -0.0058 | 0.561 | -600 | 0.741 |
| C vs B | 28 | +1 pp | 1.000 | -0.0066 | 0.005 | -1,164 | 0.009 |
| D vs B | 28 | +1 pp | 1.000 | -0.0055 | 0.031 | -811 | 0.168 |
| E vs B | 28 | +0 pp | 1.000 | -0.0054 | 0.031 | -800 | 0.114 |

### Break-even

cairn's setup is a local scan: no tokens. Per-task cost against the cold baseline:

| Condition | Per task vs A |
|---|---|
| B break-even | saves $0.0004: pays for itself from the first task |
| C break-even | saves $0.0070: pays for itself from the first task |
| D break-even | saves $0.0059: pays for itself from the first task |
| E break-even | saves $0.0058: pays for itself from the first task |

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

Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks).

| Comparison | Tasks | Success diff | p | Cost diff (USD) | p | Fresh-token diff | p |
|---|---|---|---|---|---|---|---|
| B vs A | 8 | +0 pp | 1.000 | -0.0080 | 0.312 | -1,130 | 0.461 |
| C vs A | 8 | +0 pp | 1.000 | -0.0128 | 0.148 | -2,198 | 0.055 |
| D vs A | 8 | +8 pp | 0.500 | -0.0052 | 0.312 | -1,390 | 0.312 |
| E vs A | 8 | +4 pp | 1.000 | -0.0031 | 0.742 | -1,554 | 0.250 |
| C vs B | 8 | +0 pp | 1.000 | -0.0048 | 0.383 | -1,068 | 0.250 |
| D vs B | 8 | +8 pp | 0.500 | +0.0028 | 0.742 | -260 | 1.000 |
| E vs B | 8 | +4 pp | 1.000 | +0.0049 | 0.312 | -424 | 0.641 |

### Break-even

cairn's setup is a local scan: no tokens. Per-task cost against the cold baseline:

| Condition | Per task vs A |
|---|---|
| B break-even | saves $0.0080: pays for itself from the first task |
| C break-even | saves $0.0128: pays for itself from the first task |
| D break-even | saves $0.0052: pays for itself from the first task |
| E break-even | saves $0.0031: pays for itself from the first task |

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

Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks).

| Comparison | Tasks | Success diff | p | Cost diff (USD) | p | Fresh-token diff | p |
|---|---|---|---|---|---|---|---|
| B vs A | 6 | -6 pp | 1.000 | -0.0176 | 0.438 | -2,438 | 0.156 |
| C vs A | 6 | +0 pp | 1.000 | -0.0216 | 0.156 | -975 | 0.312 |
| D vs A | 6 | +0 pp | 1.000 | -0.0185 | 0.562 | -228 | 0.844 |
| E vs A | 6 | +0 pp | 1.000 | -0.0180 | 0.312 | -1,039 | 0.438 |
| C vs B | 6 | +6 pp | 1.000 | -0.0041 | 1.000 | +1,464 | 0.031 |
| D vs B | 6 | +6 pp | 1.000 | -0.0010 | 1.000 | +2,210 | 0.031 |
| E vs B | 6 | +6 pp | 1.000 | -0.0004 | 0.844 | +1,399 | 0.031 |

### Break-even

cairn's setup is a local scan: no tokens. Per-task cost against the cold baseline:

| Condition | Per task vs A |
|---|---|
| B break-even | saves $0.0176: pays for itself from the first task |
| C break-even | saves $0.0216: pays for itself from the first task |
| D break-even | saves $0.0185: pays for itself from the first task |
| E break-even | saves $0.0180: pays for itself from the first task |

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

Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks).

| Comparison | Tasks | Success diff | p | Cost diff (USD) | p | Fresh-token diff | p |
|---|---|---|---|---|---|---|---|
| B vs A | 8 | +8 pp | 0.500 | -0.0204 | 0.109 | +486 | 0.945 |
| C vs A | 8 | +0 pp | 1.000 | -0.0211 | 0.945 | -3,909 | 0.250 |
| D vs A | 8 | +0 pp | 1.000 | -0.0344 | 0.312 | -4,094 | 0.148 |
| E vs A | 8 | +8 pp | 0.500 | -0.0278 | 0.383 | -1,831 | 0.383 |
| C vs B | 8 | -8 pp | 0.750 | -0.0006 | 1.000 | -4,395 | 0.078 |
| D vs B | 8 | -8 pp | 0.750 | -0.0140 | 0.461 | -4,580 | 0.055 |
| E vs B | 8 | +0 pp | 1.000 | -0.0074 | 0.844 | -2,317 | 0.945 |

### Break-even

cairn's setup is a local scan: no tokens. Per-task cost against the cold baseline:

| Condition | Per task vs A |
|---|---|
| B break-even | saves $0.0204: pays for itself from the first task |
| C break-even | saves $0.0211: pays for itself from the first task |
| D break-even | saves $0.0344: pays for itself from the first task |
| E break-even | saves $0.0278: pays for itself from the first task |

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

Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks).

| Comparison | Tasks | Success diff | p | Cost diff (USD) | p | Fresh-token diff | p |
|---|---|---|---|---|---|---|---|
| B vs A | 6 | -11 pp | 0.500 | -0.0027 | 0.844 | +1,926 | 0.312 |
| C vs A | 6 | +6 pp | 0.500 | -0.0064 | 0.562 | -1,888 | 0.219 |
| D vs A | 6 | -6 pp | 1.000 | +0.0094 | 0.688 | -1,094 | 0.562 |
| E vs A | 6 | +17 pp | 0.250 | +0.0028 | 0.844 | +1,069 | 0.844 |
| C vs B | 6 | +17 pp | 0.250 | -0.0037 | 0.562 | -3,814 | 0.156 |
| D vs B | 6 | +6 pp | 0.625 | +0.0121 | 1.000 | -3,020 | 0.219 |
| E vs B | 6 | +28 pp | 0.125 | +0.0055 | 0.688 | -858 | 0.688 |

### Break-even

cairn's setup is a local scan: no tokens. Per-task cost against the cold baseline:

| Condition | Per task vs A |
|---|---|
| B break-even | saves $0.0027: pays for itself from the first task |
| C break-even | saves $0.0064: pays for itself from the first task |
| D break-even | costs $0.0094 more (weigh against its success difference) |
| E break-even | costs $0.0028 more (weigh against its success difference) |

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

Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks).

| Comparison | Tasks | Success diff | p | Cost diff (USD) | p | Fresh-token diff | p |
|---|---|---|---|---|---|---|---|
| B vs A | 8 | +0 pp | 1.000 | +0.0080 | 0.023 | +1,172 | 0.055 |
| C vs A | 8 | +0 pp | 1.000 | +0.0030 | 0.547 | +287 | 0.742 |
| D vs A | 8 | +0 pp | 1.000 | +0.0048 | 0.148 | +1,372 | 0.055 |
| E vs A | 8 | +0 pp | 1.000 | +0.0044 | 0.078 | +1,062 | 0.055 |
| C vs B | 8 | +0 pp | 1.000 | -0.0050 | 0.195 | -885 | 0.109 |
| D vs B | 8 | +0 pp | 1.000 | -0.0032 | 0.742 | +200 | 0.742 |
| E vs B | 8 | +0 pp | 1.000 | -0.0036 | 0.312 | -110 | 0.844 |

### Break-even

cairn's setup is a local scan: no tokens. Per-task cost against the cold baseline:

| Condition | Per task vs A |
|---|---|
| B break-even | costs $0.0080 more (weigh against its success difference) |
| C break-even | costs $0.0030 more (weigh against its success difference) |
| D break-even | costs $0.0048 more (weigh against its success difference) |
| E break-even | costs $0.0044 more (weigh against its success difference) |

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

Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks).

| Comparison | Tasks | Success diff | p | Cost diff (USD) | p | Fresh-token diff | p |
|---|---|---|---|---|---|---|---|
| B vs A | 6 | +0 pp | 1.000 | -0.0046 | 0.688 | -528 | 1.000 |
| C vs A | 6 | +6 pp | 1.000 | -0.0062 | 0.438 | -1,174 | 1.000 |
| D vs A | 6 | +6 pp | 1.000 | -0.0038 | 1.000 | -517 | 1.000 |
| E vs A | 6 | +0 pp | 1.000 | -0.0039 | 1.000 | -448 | 0.844 |
| C vs B | 6 | +6 pp | 1.000 | -0.0017 | 0.688 | -646 | 0.844 |
| D vs B | 6 | +6 pp | 1.000 | +0.0008 | 1.000 | +11 | 1.000 |
| E vs B | 6 | +0 pp | 1.000 | +0.0007 | 1.000 | +81 | 1.000 |

### Break-even

cairn's setup is a local scan: no tokens. Per-task cost against the cold baseline:

| Condition | Per task vs A |
|---|---|
| B break-even | saves $0.0046: pays for itself from the first task |
| C break-even | saves $0.0062: pays for itself from the first task |
| D break-even | saves $0.0038: pays for itself from the first task |
| E break-even | saves $0.0039: pays for itself from the first task |

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

Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks).

| Comparison | Tasks | Success diff | p | Cost diff (USD) | p | Fresh-token diff | p |
|---|---|---|---|---|---|---|---|
| B vs A | 8 | +0 pp | 1.000 | -0.0122 | 0.023 | -1,474 | 0.109 |
| C vs A | 8 | +0 pp | 1.000 | -0.0194 | 0.008 | -2,540 | 0.023 |
| D vs A | 8 | +0 pp | 1.000 | -0.0183 | 0.023 | -2,558 | 0.016 |
| E vs A | 8 | +0 pp | 1.000 | -0.0192 | 0.016 | -2,418 | 0.023 |
| C vs B | 8 | +0 pp | 1.000 | -0.0072 | 0.109 | -1,066 | 0.195 |
| D vs B | 8 | +0 pp | 1.000 | -0.0061 | 0.195 | -1,084 | 0.250 |
| E vs B | 8 | +0 pp | 1.000 | -0.0070 | 0.109 | -944 | 0.312 |

### Break-even

cairn's setup is a local scan: no tokens. Per-task cost against the cold baseline:

| Condition | Per task vs A |
|---|---|
| B break-even | saves $0.0122: pays for itself from the first task |
| C break-even | saves $0.0194: pays for itself from the first task |
| D break-even | saves $0.0183: pays for itself from the first task |
| E break-even | saves $0.0192: pays for itself from the first task |

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

Per-task differences, two-sided Wilcoxon signed-rank (exact up to 25 tasks).

| Comparison | Tasks | Success diff | p | Cost diff (USD) | p | Fresh-token diff | p |
|---|---|---|---|---|---|---|---|
| B vs A | 6 | +0 pp | 1.000 | +0.0083 | 0.031 | +1,867 | 0.031 |
| C vs A | 6 | +0 pp | 1.000 | -0.0047 | 0.844 | -319 | 0.438 |
| D vs A | 6 | +0 pp | 1.000 | -0.0057 | 0.562 | -752 | 0.438 |
| E vs A | 6 | +0 pp | 1.000 | -0.0037 | 0.562 | -542 | 0.438 |
| C vs B | 6 | +0 pp | 1.000 | -0.0129 | 0.031 | -2,186 | 0.062 |
| D vs B | 6 | +0 pp | 1.000 | -0.0139 | 0.031 | -2,618 | 0.031 |
| E vs B | 6 | +0 pp | 1.000 | -0.0119 | 0.156 | -2,408 | 0.094 |

### Break-even

cairn's setup is a local scan: no tokens. Per-task cost against the cold baseline:

| Condition | Per task vs A |
|---|---|
| B break-even | costs $0.0083 more (weigh against its success difference) |
| C break-even | saves $0.0047: pays for itself from the first task |
| D break-even | saves $0.0057: pays for itself from the first task |
| E break-even | saves $0.0037: pays for itself from the first task |
