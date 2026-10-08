# cairn plugin for Claude Code

cairn maps every git repo in a folder and works out how they connect: HTTP and gRPC calls,
shared databases, queues and topics, packages, AWS resources, and Railway, Fly.io and Render
services. This plugin loads that map into every Claude Code session, adds the `/cairn` skill,
and starts cairn's MCP server (repo cards, related repos, cross-repo lookups).

Install, then open Claude Code inside any repo of a multi-repo folder:

```
/plugin marketplace add Moe1177/cairn
/plugin install cairn@cairn
```

Ask "which repos does this repo link to?", or type `/cairn:links`, for one line per linked
repo with its direction. If the folder has no map yet, Claude offers to build one with `/cairn` (it only reads your repos
and writes `.cairn/` in the parent folder). The plugin runs cairn from PyPI through
[uv](https://docs.astral.sh/uv/). If uv isn't installed, the first session tells you and Claude
offers to install it with uv's official installer, only if you agree; restart Claude Code after.
On Windows the plugin's scripts need Git Bash, which Claude Code normally uses. Everything stays on your machine: cairn
makes no network calls and collects no telemetry. See the main README for what cairn detects.
