# Contributing to cairn

Thanks for helping. cairn is small on purpose: one CLI, one MCP server, and deterministic
detectors, with no network calls and no telemetry.

## Set up

```bash
git clone <your fork> && cd cairn
uv sync --all-groups          # Python 3.11+; uv: https://docs.astral.sh/uv/
uv run cairn --help
```

## Before you open a pull request

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -n auto --cov=cairn --cov-fail-under=80   # -n auto: all cores (pytest-xdist)
```

CI runs the same checks on Linux, macOS, and Windows with Python 3.11–3.14. It also installs the
built wheel into a clean environment.

## How we work
- **Test first.** Write a test that fails for the reason you expect, then make it pass.
  - Bug fixes start with a test that reproduces the bug.
  - Map-quality changes go through the E1 evals in `tests/evals/` and their golden files.
- **Precision before recall.** A wrong link costs an agent more than a missing one. New
  relationship signals start as `inferred` or `ambiguous` until evidence says otherwise.
- **Treat repos as untrusted input.** Never follow links out of a repo. Never open credential
  files. Route every snippet through `security.redact`, and every rendered string through
  `security.text.clean_inline`.
- **Same output on every OS.** Store and render POSIX paths, sort on strings, and write files with
  `store.atomic.atomic_write_text`.
- **Commits** use [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`,
  `docs:`, `test:`, `refactor:`, `build:`, `ci:`).

## Benchmarks cost money

`cairn bench` drives real Claude Code sessions and uses your Claude usage: a full run of one suite
on one model is 90–120 sessions. The unit tests use a fake runner, so you never need to run a
benchmark to contribute.

## Reporting security issues

Please don't open a public issue. See [SECURITY.md](SECURITY.md).
