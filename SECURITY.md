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
- **No reading through links.** cairn never follows a symlink or junction out of a repo.
- **Redacted snippets.** Every stored snippet is redacted for common secret formats: tokens,
  connection strings, keyword assignments, bearer headers, and SQL seed values.
- **No injected instructions.** Repo-provided text (package names, README text, folder names) is
  flattened and capped, and kept out of always-loaded agent context such as `CLAUDE.md` and
  `INDEX.md`. It can't break out of cairn's marked blocks.
- **No code execution.** cairn never runs code from a repo. Git calls disable `core.fsmonitor`,
  cards never suggest shell commands for oddly named folders, and a `.cairn/` map committed inside
  a repo is never served by the MCP server.
- **No writes to your repos**, except the opt-in git hooks (`cairn hooks install`) and Cursor's
  `--per-repo` rule. These are added in marked blocks, never through links, and removed cleanly.
- **No network calls or telemetry.** Benchmarks (`cairn bench`) are the only feature that
  runs another program that talks to the network: the `claude` CLI.

If you find a way around any of these, that's a vulnerability. Please report it as described
above.
