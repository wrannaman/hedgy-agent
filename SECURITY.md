# Security and private data

This repository contains code and synthetic samples. Each user supplies their own
local account aliases and optional service credentials. It never submits orders.

Never commit `.schwab`, `.env`, filled `.env.*`, `token.json`, `accounts.local.json`,
portfolio snapshots, generated `POSITIONS.md`, state, logs, or private risk/watch
configuration. Ignore rules are a guardrail, not a secret scanner. Do not paste
credentials, OAuth redirects, or real holdings into public issues or agent chat.

`hedgy init` creates local templates with mode 0600 on POSIX systems; OAuth writes
use a restrictive umask and token mode 0600. Windows users should use an account-private
checkout and Windows file permissions. Scans never start interactive OAuth.
`hedgy auth` is the explicit user-terminal login path.

The commit hook scans staged changes with Gitleaks before running tests. Enable it
with `git config core.hooksPath .githooks`. CI also scans history. Before publishing:

```sh
gitleaks git . --pre-commit --staged --redact=100 --no-banner
gitleaks git . --redact=100 --log-opts='--all' --no-banner
```

Do not run directory scans across a live installation's secrets or private reports.
If a secret is exposed, revoke it at the issuer before removing it from Git history.
For a sensitive vulnerability, use GitHub's private vulnerability reporting under
this repository's Security tab when available; do not disclose credentials in a public issue.

The optional scheduler runs a headless Claude CLI with permission prompts disabled.
Review its runbook and local access before explicitly enabling it. It produces
research and optional Slack notifications only. Runtime risk blocks may be added by
an agent, but only the account owner may clear them against their documented criteria.
