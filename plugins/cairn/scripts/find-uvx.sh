# Sourced by the plugin's scripts. find_uvx prints the uvx to run cairn with, or fails.
# Besides PATH it looks where uv's installer and pip put uv, so a uv that isn't on PATH (pip's
# per-user Scripts folder often isn't) or was installed during this session still works: Claude
# Code's PATH was fixed when it started.
CAIRN_PIN="cairnmap==0.8.2"

find_uvx() {
  if command -v uvx >/dev/null 2>&1; then
    command -v uvx
    return 0
  fi
  local dir name
  # uv's installer, then pip --user (Windows, macOS), then pip into a Windows python.org install.
  for dir in "${XDG_BIN_HOME:-}" "${HOME:-}/.local/bin" "${USERPROFILE:-}/.local/bin" \
    "${CARGO_HOME:-${HOME:-}/.cargo}/bin" \
    "${APPDATA:-}"/Python/Python3*/Scripts "${HOME:-}"/Library/Python/3.*/bin \
    "${LOCALAPPDATA:-}"/Programs/Python/Python3*/Scripts; do
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

# Prepend the fallback uv install folders to PATH so scripts can run uvx by name.
# The plugin directory validator requires the launched program to be spelled literally,
# so scripts use this instead of resolving uvx into a variable via find_uvx.
add_uv_dirs_to_path() {
  local dir
  # uv's installer, then pip --user (Windows, macOS), then pip into a Windows python.org install.
  for dir in "${XDG_BIN_HOME:-}" "${HOME:-}/.local/bin" "${USERPROFILE:-}/.local/bin" \
    "${CARGO_HOME:-${HOME:-}/.cargo}/bin" \
    "${APPDATA:-}"/Python/Python3*/Scripts "${HOME:-}"/Library/Python/3.*/bin \
    "${LOCALAPPDATA:-}"/Programs/Python/Python3*/Scripts; do
    [ -n "$dir" ] && [ -d "$dir" ] || continue
    case ":$PATH:" in
      *":$dir:"*) ;;
      *) PATH="$dir:$PATH" ;;
    esac
  done
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
