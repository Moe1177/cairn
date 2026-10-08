#!/usr/bin/env bash
# MCP server entry for the Claude Code plugin: run the pinned cairn release through uv.
# The plugin directory validator requires the loader command to be a literal
# ${CLAUDE_PLUGIN_ROOT}/<file> path, so .mcp.json points here instead of at bare uvx.
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=find-uvx.sh
. "$here/find-uvx.sh"

# Spell uvx by name for the plugin directory validator (see session-start.sh):
# extend PATH with the usual uv install spots instead of resolving it into a variable.
add_uv_dirs_to_path

if ! command -v uvx >/dev/null 2>&1; then
  echo "cairn: the MCP server needs uv (https://docs.astral.sh/uv/) but couldn't find it." >&2
  echo "Install it with: $(uv_install_command)" >&2
  exit 127
fi
export CAIRN_PLUGIN=1
# Version pinned literally: the plugin directory validator cannot follow variables.
exec uvx --from cairnmap==0.8.2 cairn serve --from "${CLAUDE_PROJECT_DIR}"
