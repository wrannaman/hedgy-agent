# Hedgy

An options research bot. It finds rich options and sends me trade ideas.
I still approve every single order by hand.

The code also analyzes portfolio snapshots. It never submits orders.

Experimental. Not financial advice. **Do not use with real money.** Assume complete
loss of any capital exposed; options and leverage can lose more than the initial
capital. Provided without warranty. [Full disclaimer](docs/DISCLAIMER.md).

## Install

Python 3.11–3.13 on macOS or Linux:

```sh
git clone https://github.com/wrannaman/hedgy-agent.git
cd hedgy-agent
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/hedgy demo
```

The offline demo uses synthetic holdings and prints its report directory. No
account or API key is needed. Run `.venv/bin/hedgy doctor` to check your setup.

## Portfolio analysis

```sh
.venv/bin/hedgy init
# Configure trading/accounts.local.json and add CSVs to trading/positions/.
.venv/bin/hedgy portfolio sweep --positions-dir trading/positions
.venv/bin/hedgy portfolio rebalance --positions-dir trading/positions --target 5000
```

Any broker's normalized CSV works. See the [CSV format](trading/examples/README.md).
Reports use snapshot prices by default. Missing cost basis is excluded from tax
calculations; review tax assumptions before interpreting cash-raise estimates.

Live options research requires an optional Schwab connection. See
[setup](docs/SETUP.md), [configuration](docs/CONFIGURATION.md), and
[strategy rules](trading/strategies/csp_401k/RULES.md). Scheduling is optional and
never enabled by installation. The CSP policy can deploy the entire configured
cash sleeve; read the rules before running live research.

## Development

```sh
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/hedgy test
```

Use the isolated test harness. See [CONTRIBUTING.md](CONTRIBUTING.md) and
[SECURITY.md](SECURITY.md). [MIT license](LICENSE).

Choose Claude Code or Codex CLI for scheduled research: [agent configuration](trading/deploy/AGENT_PROVIDERS.md).
