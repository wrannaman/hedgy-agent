# portfolio_watch

Recommendation-only cross-account portfolio watch.

This strategy reads the newest Schwab position CSV per account from `../../positions/`, normalizes holdings, optionally enriches them with live quotes, and writes a compact morning context file.

It never places orders. It exists to answer: “given what the account owner already owns, what should affect today's decision?”

## Run

```bash
trading/.venv/bin/python3 trading/strategies/portfolio_watch/sweep.py
```

For offline parsing and tests:

```bash
trading/.venv/bin/python3 trading/strategies/portfolio_watch/sweep.py --no-quotes
```

## Outputs

- `state/latest.json`: normalized accounts, holdings, exposure by symbol, flags, and summary.
- `state/latest_summary.txt`: one short line for the morning Slack recap.

## Current Flags

- Stale CSV export.
- Idle cash or money-market balance.
- Large daily move.
- Large unrealized loser.
- Large unrealized winner.
- Account concentration.
- Cross-account symbol overlap.
