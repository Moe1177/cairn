# Security policy

## Reporting a vulnerability

Please report security issues privately using GitHub's **Report a vulnerability** button, on the
repository's **Security** tab (private vulnerability reporting). Don't open a public issue.

We aim to acknowledge reports within 7 days and to ship a fix or mitigation for confirmed
high-severity issues within 30 days. With your permission, we credit reporters in the changelog.

## Supported versions

Only the latest release gets security fixes until 1.0.

## Threat model

cairn reads every repository in a folder. Those repos may come from anywhere, so cairn treats
their contents as **untrusted input**. These guarantees are tested:

- **No secrets from files.** cairn never opens `.env` files (only `.env.example`-style
  templates), private keys, or credential files (`.npmrc`, `.pgpass`, kubeconfig, Terraform state,
  `*secret*.yaml`, and others).
- **No reading through links.** cairn never reads or writes through a symlink or junction
  anywhere inside a repo.
- **Redacted snippets.** Every stored snippet is redacted for common secret formats: tokens,
  connection strings, keyword assignments, bearer headers, and SQL seed values.
- **No injected instructions.** README text never enters always-loaded agent context
  (`CLAUDE.md`, `INDEX.md`). The names that do appear there (folder names, package names) are
  flattened to one line, capped, and stripped of comment markers and backticks. Package names
  must also look like package names. None of this text can break out of cairn's marked blocks.
- **No code execution.** cairn never runs code from a repo:
  - Every git call disables the repo-configurable features that run programs: `core.fsmonitor`,
    hooks, and the clean/smudge/process filters defined in the repo's own config.
  - Git calls also take no optional locks.
  - Cards never suggest shell commands for oddly named folders.
  - A `.cairn/` map committed inside a repo is never served by the MCP server.
- **No writes to your repos**, except the opt-in git hooks (`cairn hooks install`) and Cursor's
  `--per-repo` rule. These are added in marked blocks, never through links, and removed cleanly.
- **No network calls or telemetry.** Benchmarks (`cairn bench`) are the only feature that
  runs another program that talks to the network: the `claude` CLI.

If you find a way around any of these, that's a vulnerability. Please report it as described
above.
