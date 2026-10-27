# morning_decision

Deterministic first-pass decision engine for the morning trading workflow.

It reads:

- `strategies/csp_401k/state/last_screen.json`
- `strategies/csp_401k/state/trade_log.json`
- `strategies/portfolio_watch/state/latest.json`

It writes:

- `state/morning_decision.json`
- `state/morning_decision.txt`

The output is not an order. It is the structured recommendation the morning agent should review, news-check, and format.

## Run

```bash
trading/.venv/bin/python3 trading/strategies/morning_decision/decide.py
```
