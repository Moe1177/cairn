## What and why

<!-- What does this change, and what problem does it solve? Link the issue if there is one. -->

## How it was tested

<!-- Name the test you wrote first and what it failed on before the change. -->

## Checklist

- [ ] A test fails without this change and passes with it
- [ ] `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest` pass
- [ ] Output is the same on Windows, macOS, and Linux (POSIX paths, string sorting)
- [ ] Repo content is treated as untrusted (no link-following, snippets redacted, text cleaned)
- [ ] `CHANGELOG.md` updated under **Unreleased** if users will notice the change
