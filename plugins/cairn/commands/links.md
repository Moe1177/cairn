---
description: List the repos this repo (or the one you name) is linked to, and in which direction
argument-hint: "[repo]"
---

Call the cairn MCP `links` tool with repo set to "$ARGUMENTS" (leave it empty for the repo this
session is in). Reply with its output exactly as it comes back, inside a code block, and nothing
else. If the tool isn't available, run `cairn links $ARGUMENTS` and show that output instead.
