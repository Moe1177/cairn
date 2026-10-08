@echo off
rem The plugin's MCP server on Windows. .mcp.json names scripts/mcp-serve, and Claude Code runs
rem this file in its place there: Windows can't run that bash script directly (`bash` on PATH is
rem often WSL's). It finds uv like find-uvx.sh: on PATH, else where uv's installer or pip puts it.
rem Nothing may reach stdout before cairn starts: it is the MCP channel. No labels or goto: the
rem repository checks this file out with LF line endings.
setlocal
set "UVX_DIR="
where /q uvx
if errorlevel 1 (
  for %%D in ("%XDG_BIN_HOME%" "%USERPROFILE%\.local\bin" "%CARGO_HOME%\bin" "%USERPROFILE%\.cargo\bin") do (
    if not defined UVX_DIR if not "%%~D"=="" if not "%%~D"=="\bin" if exist "%%~D\uvx.exe" set "UVX_DIR=%%~D"
  )
  for /d %%D in ("%APPDATA%\Python\Python3*" "%LOCALAPPDATA%\Programs\Python\Python3*") do (
    if not defined UVX_DIR if exist "%%~D\Scripts\uvx.exe" set "UVX_DIR=%%~D\Scripts"
  )
)
if defined UVX_DIR set "PATH=%UVX_DIR%;%PATH%"
where /q uvx
if errorlevel 1 (
  echo cairn plugin: couldn't find uv ^(https://docs.astral.sh/uv/^), so cairn's MCP server can't start. 1>&2
  echo Install it with: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex", then restart Claude Code. 1>&2
  exit /b 127
)
if not defined CLAUDE_PROJECT_DIR set "CLAUDE_PROJECT_DIR=%CD%"
set "CAIRN_PLUGIN=1"
uvx --from cairnmap==0.8.2 cairn serve --from "%CLAUDE_PROJECT_DIR%" %*
