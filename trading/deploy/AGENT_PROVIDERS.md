# Choose the research agent

The scheduler supports Claude Code and Codex CLI. Both execute the same
`CRON_PROMPT.md`, and both must pass the same fresh scan, screen, and decision
checks before Python publishes a recommendation. Provider errors never trigger
an automatic switch to another provider.

Copy `trading/.env.agent.example` to `trading/.env.agent` and choose:

```sh
AGENT_PROVIDER=claude
CLAUDE_MODEL=claude-opus-5-5
```

or:

```sh
AGENT_PROVIDER=codex
# Optional: CODEX_MODEL=your-model-id
```

Claude defaults to Opus 5.5. Codex uses the authenticated CLI's configured model
unless `CODEX_MODEL` is set. `AGENT_MODEL` overrides either provider's model.
`CLAUDE_BIN` and `CODEX_BIN` accept executable paths. Both CLIs should normally
be on PATH or in `~/.local/bin`. Local file settings override inherited variables.
Install only the CLI you intend to use and authenticate it on the scheduler host
with `claude` or `codex login`. Authentication belongs to the CLI, not the example
config. Never commit credentials or the filled local config.

From `trading/strategies/csp_401k`, check the selected provider:

```sh
REPO_ROOT="$(cd ../.. && pwd)"
source ./agent_provider.sh
"${AGENT_PROBE_CMD[@]}"
```

A healthy probe prints exactly `PONG`. Provider-specific diagnostics go to
`logs/claude-probe-YYYY-MM-DD.log` or `logs/codex-probe-YYYY-MM-DD.log` during
scheduled runs. The active provider and model are recorded in the dated cron log.
`AGENT_TIMEOUT` sets seconds per attempt (default 1200); `AGENT_MAX_ATTEMPTS`
sets the maximum attempts (default 2). Stop an active run before changing provider;
an existing run retains its selection.

The headless run requires shell execution, writes, and market-data network
access. Claude uses its permission-skipping mode; Codex uses `codex --search exec
--sandbox danger-full-access`, which is noninteractive and allows networked
commands. Use a dedicated, trusted checkout and review the runbook before enabling
a schedule. These settings allow tools to execute; the runbook prohibits orders,
code changes, and agent-sent messages. Python remains the publishing authority.
See the [official Codex noninteractive documentation](https://learn.chatgpt.com/docs/non-interactive-mode).

Changing the provider does not install a schedule or change strategy rules.
