# Sourced by the plugin's scripts. put_uvx_on_path makes a plain `uvx` runnable, or fails.
# Besides PATH it looks where uv's installer and pip put uv, so a uv that isn't on PATH (pip's
# per-user Scripts folder often isn't) or was installed during this session still works: Claude
# Code's PATH was fixed when it started. A uv found there has its folder added to PATH.

put_uvx_on_path() {
  command -v uvx >/dev/null 2>&1 && return 0
  local dir name
  # uv's installer, then pip --user (Windows, macOS), then pip into a Windows python.org install.
  for dir in "${XDG_BIN_HOME:-}" "${HOME:-}/.local/bin" "${USERPROFILE:-}/.local/bin" \
    "${CARGO_HOME:-${HOME:-}/.cargo}/bin" \
    "${APPDATA:-}"/Python/Python3*/Scripts "${HOME:-}"/Library/Python/3.*/bin \
    "${LOCALAPPDATA:-}"/Programs/Python/Python3*/Scripts; do
    [ -n "$dir" ] || continue
    for name in uvx uvx.exe; do
      if [ -f "$dir/$name" ] && [ -x "$dir/$name" ]; then
        # Git Bash: C:\Users\... has a colon, which would split PATH.
        if command -v cygpath >/dev/null 2>&1; then
          dir="$(cygpath -u "$dir")"
        fi
        PATH="$dir:$PATH"
        export PATH
        command -v uvx >/dev/null 2>&1 && return 0
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
