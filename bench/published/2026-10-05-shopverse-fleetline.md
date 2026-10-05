# cairn benchmark results (2026-10-05)

Headless Claude Code (`cairn bench`), read-only tools, your own CLAUDE.md/rules excluded, a fresh
copy of the workspace per run. Answers re-graded with the final deterministic grader.

**Read with care:** 3 runs per cell, small synthetic workspaces (6 and 15 repos), no significance
testing yet. These numbers show direction, not proof.

Conditions: **A** no map · **B** a hand-written RELATED_REPOS-style CLAUDE.md · **C** cairn's
INDEX only · **D** INDEX + repo cards · **E** D + cairn's MCP server.

### shopverse — Haiku 4.5

| Condition | Success | Cost / task | vs A | Turns |
|---|---|---|---|---|
| A no map | 16/18 (89%) | $0.0554 | — | 9.8 |
| B hand-written doc | 14/18 (78%) | $0.0329 | -41% | 5.2 |
| C cairn INDEX | 18/18 (100%) | $0.0577 | +4% | 6.3 |
| D INDEX + cards | 18/18 (100%) | $0.0320 | -42% | 9.0 |
| E + MCP | 18/18 (100%) | $0.0348 | -37% | 8.3 |

### shopverse — Sonnet 5.5 *

| Condition | Success | Cost / task | vs A | Turns |
|---|---|---|---|---|
| A no map | 18/18 (100%) | $0.0544 | — | 5.4 |
| B hand-written doc | 17/18 (94%) | $0.0445 | -18% | 4.3 |
| C cairn INDEX | 18/18 (100%) | $0.0413 | -24% | 3.9 |
| D INDEX + cards | 18/18 (100%) | $0.0473 | -13% | 4.8 |
| E + MCP | 18/18 (100%) | $0.0493 | -9% | 4.7 |

### shopverse — Opus 5.5 *

| Condition | Success | Cost / task | vs A | Turns |
|---|---|---|---|---|
| A no map | 18/18 (100%) | $0.0832 | — | 5.1 |
| B hand-written doc | 18/18 (100%) | $0.0999 | +20% | 6.1 |
| C cairn INDEX | 18/18 (100%) | $0.0771 | -7% | 4.1 |
| D INDEX + cards | 18/18 (100%) | $0.0856 | +3% | 4.8 |
| E + MCP | 18/18 (100%) | $0.0864 | +4% | 4.6 |

### fleetline — Haiku 4.5

| Condition | Success | Cost / task | vs A | Turns |
|---|---|---|---|---|
| A no map | 23/24 (96%) | $0.0394 | — | 8.3 |
| B hand-written doc | 23/24 (96%) | $0.0271 | -31% | 5.9 |
| C cairn INDEX | 24/24 (100%) | $0.0366 | -7% | 6.2 |
| D INDEX + cards | 21/24 (88%) | $0.0378 | -4% | 5.0 |
| E + MCP | 24/24 (100%) | $0.0363 | -8% | 4.9 |

### fleetline — Sonnet 5.5

| Condition | Success | Cost / task | vs A | Turns |
|---|---|---|---|---|
| A no map | 24/24 (100%) | $0.0463 | — | 3.9 |
| B hand-written doc | 24/24 (100%) | $0.0529 | +14% | 5.0 |
| C cairn INDEX | 24/24 (100%) | $0.0458 | -1% | 3.9 |
| D INDEX + cards | 24/24 (100%) | $0.0451 | -3% | 3.1 |
| E + MCP | 24/24 (100%) | $0.0492 | +6% | 4.1 |

\* Sonnet and Opus on shopverse ran before the owner-link fix (cairn 0.1.0 pre-release): their
D/E cards hid the `orders` consumers. Haiku on shopverse was re-run after the fix.

## What we take from this

- **Weaker models gain the most accuracy.** Haiku with the cairn INDEX (C) or the MCP server (E)
  answered every task correctly on both suites; with no map it missed 4–11%.
- **The INDEX alone is the most reliable condition** across models and suites (100% everywhere).
- **Cost effects are small on small workspaces:** cairn conditions (C–E) ranged from −42% to +6%
  vs no map, depending on the model.
  Strong models with grep explore a 6–15 repo workspace in ~4 turns; cairn's savings should grow
  with workspace size, which these suites don't yet show.
- **A hand-written doc is cheap but unreliable:** models answer from it without checking, and a
  vague or stale line becomes a wrong answer.

## Runs

- shopverse / Haiku 4.5: claude-haiku-4-5-20251001; 2.1.289 (Claude Code); 3 runs × 6 tasks × 5 conditions; 2026-10-05T15:55:21+00:00
- shopverse / Sonnet 5.5 *: claude-sonnet-5-5; 2.1.289 (Claude Code); 3 runs × 6 tasks × 5 conditions; 2026-10-05T15:03:25+00:00
- shopverse / Opus 5.5 *: claude-opus-5-5; 2.1.289 (Claude Code); 3 runs × 6 tasks × 5 conditions; 2026-10-05T15:03:25+00:00
- fleetline / Haiku 4.5: claude-haiku-4-5-20251001; 2.1.289 (Claude Code); 3 runs × 8 tasks × 5 conditions; 2026-10-05T15:55:21+00:00
- fleetline / Sonnet 5.5: claude-sonnet-5-5; 2.1.289 (Claude Code); 3 runs × 8 tasks × 5 conditions; 2026-10-05T15:55:21+00:00
