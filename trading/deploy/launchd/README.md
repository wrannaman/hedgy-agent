# Optional macOS research scheduler

Core CSV analysis and tests do not need launchd or an agent subscription. This
advanced path is opt-in: it runs a headless Claude CLI with permission prompts
disabled, local read-only Schwab data access, and optional Slack delivery.
Review its runbook and local access before enabling. Never submit orders.

Prerequisites: a source checkout with root `.venv`, `.[schwab]`, explicit
`hedgy auth`, reviewed strategy policy/account scope, authenticated `claude` on PATH,
and `SLACK_TRADING_WEBHOOK` if you want successful recap delivery. The script uses
the CLI's default model; optional `CLAUDE_MODEL` / `CLAUDE_BIN` override it. It never
reads a shell profile for an OAuth token. Authenticate the CLI through its own setup.

The machine timezone must be America/Los_Angeles for these Pacific schedules:

| Job | Schedule, weekdays | Purpose |
| --- | --- | --- |
| `hedgy-agent.morning-roam` | 6:35 AM; also at load | Full research + one recap; fresh-output guards and deduplication |
| `hedgy-agent.intraday-roam` | 7:00, 9:30, 11:30 AM, 12:30 PM | Recheck; notify only for a new ticket |
| `hedgy-agent.watchdog` | 8:00 AM | Alarm if no successful morning completion stamp |

Templates contain `__TRADING_ROOT__`; the installer renders this checkout's paths.
It creates per-user jobs, with no sudo. It may start the morning run immediately:

```sh
bash trading/deploy/launchd/install.sh
launchctl list | grep hedgy-agent
```

Do not bootstrap template files directly. The morning script checks market dates,
authentication, freshness, retry bounds, and the completion stamp. It writes private
logs under the strategy and delegates notification to one poster. A missing webhook
is not recorded as successful Slack delivery.

To stop this installation's jobs:

```sh
for name in morning-roam intraday-roam watchdog; do
  launchctl bootout "gui/$(id -u)/hedgy-agent.$name"
  launchctl disable "gui/$(id -u)/hedgy-agent.$name"
done
```

One public checkout owns these labels. They are distinct from legacy private
`fund.*` jobs. The installer must be invoked deliberately; demo/init never runs it.
