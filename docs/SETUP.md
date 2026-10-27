# Setup paths

## CSV-only: no broker account required

Clone the repository or extract its source ZIP. Python 3.11–3.13 is supported.
Create `.venv` in the checkout, install with `python -m pip install -e .`, then
run `hedgy doctor` and `hedgy demo` using that environment's executables.
This editable checkout is the supported installation: strategies and local state
remain alongside their reviewed source. A standalone wheel is not a complete
strategy workspace and the CLI reports that explicitly.

`hedgy init` creates private templates without overwriting existing settings.
Only `accounts.local.json` is needed for CSV-only work; leave `.schwab` blank.
Convert your broker's export to the [normalized CSV schema](../trading/examples/README.md).
Original Schwab position exports are also supported. Use `hedgy portfolio sweep`
or `hedgy portfolio rebalance`; they are offline unless you add `--live-quotes`.

## Optional Schwab integration

If you do not have a Schwab account, the CSV-only path remains fully usable. For
the current live options and quote integration:

1. Open an eligible account with [Schwab](https://www.schwab.com/), if needed.
2. Register at [Schwab Developer](https://developer.schwab.com/). Request access
   to the Trader API's account and market-data products and create an app. Access
   depends on Schwab approval; this software does not bypass that process.
3. Configure the callback for your app, matching `SCHWAB_CALLBACK_URL` exactly
   (the local template uses `https://127.0.0.1:8182`).
4. Install the integration and generate templates:

```sh
.venv/bin/python -m pip install -e '.[schwab]'
.venv/bin/hedgy init
```

The account owner edits `trading/.schwab` locally with their key, secret, and
callback. Set `SCHWAB_ACCOUNT_SUFFIX` in `trading/.env.local` to the intended
options account's suffix. An absent or ambiguous suffix is an error; account list
order never determines selection. Put that suffix's tax/bucket metadata in
`accounts.local.json` when analyzing an original Schwab CSV.

The **user**, in an interactive terminal, runs:

```sh
.venv/bin/hedgy auth
.venv/bin/hedgy doctor --live
```

Complete the OAuth flow in that terminal. Do not paste redirect URLs into an
agent conversation. Tokens stay in ignored `trading/token.json`; refresh tokens
expire, so repeat explicit login when needed. Background scans never open a login
prompt. `doctor --live` checks configuration presence, not token validity or API
permissions; a real scan verifies connectivity.

Read `trading/strategies/csp_401k/AGENTS.md`, `RULES.md`, and `rules.py` before
live research. The inherited sizing policy is concentrated and may use all
available strategy cash. This account scope and policy must be reviewed by its
owner; installing Hedgy does not approve a strategy or any order.

To run individual research scripts, use the checkout environment and read their
usage/docs. For example, from `trading/strategies/csp_401k/`:

```sh
../../../.venv/bin/python daily_scan.py
../../../.venv/bin/python screener.py
```

These can make many data requests. They recommend and log; they never place orders.

## Optional Finnhub / Slack

`FINNHUB_API_KEY` enables earnings data. `SLACK_TRADING_WEBHOOK` enables the
explicit notification paths. Set them in the process environment or the ignored
`.schwab` settings file. Neither is needed for portfolio CSVs or tests. Missing
Slack configuration means no delivery; it is not a successful posted recap.

For a local price watcher, copy `trading/price-watch.example.json` to ignored
`trading/price-watch.local.json`, replace its dummy symbol and levels, then review
it before enabling. No watcher configuration means no requests or notifications.

## Optional macOS scheduler

This advanced integration requires macOS, an authenticated Claude CLI, Schwab
login, and a chosen Slack notification destination. Core research and CSV tools
work without Claude or launchd. See [scheduler instructions](../trading/deploy/launchd/README.md).
No install, demo, or initializer enables scheduling automatically.
