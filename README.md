# Hedgy Agent

[hedgy.fund](https://hedgy.fund) · [Agent quickstart](docs/AGENT_QUICKSTART.md)

**Give your agent a research desk, not your brokerage password.**

Hedgy turns portfolio snapshots and market data into explainable research and
recommendations. Start with a working offline portfolio demo, then add your own
holdings or optional Schwab options data. It never submits orders.

## First useful result

Python **3.11–3.13**. macOS, Linux, or Windows with a terminal. From a clone or
[downloaded ZIP](https://github.com/wrannaman/hedgy-agent/archive/refs/heads/main.zip):

```sh
git clone https://github.com/wrannaman/hedgy-agent.git
cd hedgy-agent
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/hedgy demo
```

On Windows use `py -3 -m venv .venv`, then `.venv\Scripts\python -m pip install -e .`
and `.venv\Scripts\hedgy demo`. No account, API key, agent subscription, or network
access is needed **after installation**. The command prints `DEMO OK` and a report
folder containing concentration, cash, gain/loss, and cash-raise analysis for
synthetic holdings. It creates a new temporary directory each time.

### Hand it to your agent

Copy this into Codex, Claude Code, or another coding agent in the checkout:

> Read AGENTS.md and docs/AGENT_QUICKSTART.md. Set up this checkout in a local
> virtual environment, run the offline demo and doctor, then explain the sample
> portfolio report. Keep credentials and real holdings out of chat and Git.
> Help me choose CSV-only portfolio analysis or the optional Schwab integration.
> Do not enable notifications, scheduling, or place orders.

## Use your own portfolio

```sh
.venv/bin/hedgy init
# Edit trading/accounts.local.json with local aliases and tax/bucket metadata.
# Save broker-independent CSV snapshots in ignored trading/positions/.
.venv/bin/hedgy portfolio sweep --positions-dir trading/positions
.venv/bin/hedgy portfolio rebalance --positions-dir trading/positions --target 5000
```

CSV analysis is offline by default and works with any broker. See the
[input schema and sample](trading/examples/README.md). Missing cost basis stays
unknown and is excluded from tax calculations. Review the example tax assumptions
before using a cash-raise estimate.

## What is inside

- **Portfolio watch:** concentration, cash, price moves, gains/losses, tax-aware
  cash-raise planning, and trailing-stop review items.
- **Options research:** cash-secured-put screening and position management,
  covered-call recommendations, catalyst checks, and decision journals.
- **Research sleeves:** index variance premium, trend, factor tilts, and
  post-earnings drift. These are research modules, not plug-and-play mandates.
- **Optional scheduled agent:** macOS launchd + Claude CLI for a daily research
  pass and Slack recap. Installation never enables it automatically.

[Schwab setup](docs/SETUP.md) · [Configuration](docs/CONFIGURATION.md) ·
[Agent quickstart](docs/AGENT_QUICKSTART.md) · [Architecture](docs/ARCHITECTURE.md)

Live options scanning currently uses Schwab quotes and chains. Another broker's
CSV works today; replacing the live options data provider requires an adapter.
The inherited CSP sizing policy can deploy the entire configured cash sleeve.
Read its [rules](trading/strategies/csp_401k/RULES.md) before enabling live research.
This is experimental research software, not personalized financial advice or a
promise of returns. You own every investment decision and order.

## Contribute

```sh
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/hedgy test
```

`hedgy test` preserves per-strategy import isolation. Tests and demos need no
credentials and must never contact brokerage or notification services.
See [CONTRIBUTING.md](CONTRIBUTING.md) for checks and [SECURITY.md](SECURITY.md)
for private-data handling. MIT licensed.
