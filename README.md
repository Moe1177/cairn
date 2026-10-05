# cairn

> Cairns are stacked-stone trail markers. cairn places small, cheap markers that
> guide coding agents to the right repo, and then to the right file.

When you mention a repo that isn't in your agent's working directory, the agent
usually doesn't know what you mean, so it explores, greps, and burns tokens.
cairn maps every git repo under a folder once, then hands your agent a tiny
index plus one short card per repo.

## Quick start

```bash
# from the folder that contains your repos
uvx --from cairnmap cairn init        # or: pipx install cairnmap && cairn init
```

`cairn init` scans every git repo under the folder, writes `.cairn/`, and offers
to add the index to `CLAUDE.md` in that folder. Claude Code reads parent
`CLAUDE.md` files, so every repo inside now knows about its siblings.

## What it writes

| Path | What it is |
|---|---|
| `.cairn/INDEX.md` | One line per repo (~25 tokens): name, aliases, purpose, stack |
| `.cairn/cards/<repo>.md` | ≤800-token card: summary, run commands, layout, relationships with evidence |
| `.cairn/workspace.json` | The full graph (repos, contracts, scored edges) |
| `.cairn/relations.yaml` | **Yours:** extra aliases, manual links, notes, ignored repos |
| `.cairn/authored/<repo>.yaml` | **Yours:** summaries and edge explanations (kept across scans) |

Relationships come from package dependencies, shared database tables, `../`
path references, and docs that mention sibling repos. Each relationship is
tagged `extracted`, `inferred`, or `ambiguous`, so agents know how far to
trust it.

## Commands

`cairn scan` · `cairn init` · `cairn status` · `cairn annotate-edge` · `cairn install claude` · `cairn uninstall claude`

### Unconfirmed links

Name-only matches (two repos that both create a `profiles` table, two packages
published under the same name, a default local Supabase id) are tagged
`ambiguous` and hidden from cards. Repos on different hosted databases (e.g.
Neon vs Supabase) are never linked by table names at all. `cairn status` lists
what's left; settle each one once:

```bash
cairn annotate-edge "shopapp->resumeapp:shares_db" --reject --why "different databases"
cairn annotate-edge "web->api:shares_db" --confirm
```

Decisions are stored in `.cairn/authored/` and survive every re-scan.

## Safety

- cairn never modifies your repos.
- It never opens `.env` files (only `.env.example`-style templates, and only for names), keys, or credential files.
- Evidence snippets are redacted, and git remotes are stored without credentials.

## Roadmap

1. **Core map** (this release): INDEX, cards, relationships, Claude Code.
2. MCP server, `/cairn` skill, refresh, Codex/Gemini/Cursor integrations.
3. Deep per-repo queries via [graphify](https://github.com/Graphify-Labs/graphify).
4. Published benchmarks proving the token savings.

## License

Apache-2.0
