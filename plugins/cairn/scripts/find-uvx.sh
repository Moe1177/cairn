# Sourced by the plugin's scripts. find_uvx prints the uvx to run cairn with, or fails.
# Besides PATH it looks where uv's installer puts uv, so a uv installed during this session
# works at once: Claude Code's PATH was fixed when it started.
CAIRN_PIN="cairnmap==0.8.1"

find_uvx() {
  if command -v uvx >/dev/null 2>&1; then
    command -v uvx
    return 0
  fi
  local dir name
  for dir in "${XDG_BIN_HOME:-}" "${HOME:-}/.local/bin" "${USERPROFILE:-}/.local/bin" \
    "${CARGO_HOME:-${HOME:-}/.cargo}/bin"; do
    [ -n "$dir" ] || continue
    for name in uvx uvx.exe; do
      if [ -f "$dir/$name" ] && [ -x "$dir/$name" ]; then
        printf '%s\n' "$dir/$name"
        return 0
      fi
    done
  done
  return 1
}

# The official uv installer for this OS (https://docs.astral.sh/uv/getting-started/installation/).
uv_install_command() {
  case "$(uname -s 2>/dev/null)" in
    MINGW* | MSYS* | CYGWIN*)
      printf '%s' 'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
      ;;
    *) printf '%s' 'curl -LsSf https://astral.sh/uv/install.sh | sh' ;;
  esac
}
