#!/usr/bin/env bash
# The plugin's session-start hook. With uv: cairn's context for this session. Without uv: a
# warning for the user, and a note asking Claude to offer, once, to install uv for them. Claude
# installs it only if the user agrees (and Claude Code asks before running the installer).
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=find-uvx.sh
. "$here/find-uvx.sh"

if uvx="$(find_uvx)"; then
  exec "$uvx" --from "$CAIRN_PIN" cairn context
fi

json_string() {
  local s=${1//\\/\\\\}
  s=${s//\"/\\\"}
  printf '"%s"' "$s"
}

install="$(uv_install_command)"
warning="cairn plugin: uv isn't installed, so cairn can't run yet. Claude can install it for you if you agree, or see https://docs.astral.sh/uv/getting-started/installation/"
context="cairn: the cairn plugin can't run because uv (https://docs.astral.sh/uv/) isn't installed; cairn runs from PyPI through it. Tell the user, and offer once to install uv with its official installer: \`$install\`. Run it only if the user agrees, and don't offer again if they decline. After it's installed, tell them to restart Claude Code so cairn's MCP server can find uv."

echo "$warning" >&2
printf '{"systemMessage": %s, "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": %s}}\n' \
  "$(json_string "$warning")" "$(json_string "$context")"
