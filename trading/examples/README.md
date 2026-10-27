# Broker-independent portfolio snapshots

Use one CSV per account per snapshot date. Export positions from your broker and
convert columns to this schema, or maintain a spreadsheet and save it as CSV.
Place private files in `trading/positions/` (ignored), or pass `--positions-dir`.

| Column | Meaning |
| --- | --- |
| `account_id` | Your local alias, such as `my-brokerage`; no real account number needed |
| `account_name` | Display name; identical on every row in the file |
| `as_of` | Snapshot date in `YYYY-MM-DD` format; identical on every row |
| `symbol` | Stock/ETF ticker; `CASH` for a cash row |
| `quantity` | Share count or cash units; may be blank when unavailable |
| `price` | Snapshot price; may be blank when unavailable |
| `market_value` | Required dollar value; signed for liabilities/short positions |
| `cost_basis` | Optional total basis in dollars; blank means unknown, not zero |
| `asset_type` | `equity`, `etf`, `option`, or `cash`; defaults to `equity` |
| `description` | Optional holding description |
| `day_change_pct` | Optional daily percentage change |
| `day_change_dollars` | Optional daily dollar change |

`quantity`, `price`, and `market_value` columns must be present. For options,
market value must already include the contract multiplier. Use plain numbers;
quote fields containing commas. Each file must contain at least one holding.
The newest `as_of` wins per account alias; keep one snapshot per account per day.
Future dates, mixed accounts/dates, and missing market values are rejected.

Copy `accounts.example.json` to `accounts.local.json` in `trading/`. Replace its
example account keys with your aliases. `tax_treatment` must be `taxable`,
`tax_deferred`, or `tax_free`. `bucket` can be any name: accounts sharing one bucket
are grouped for concentration analysis. Account mappings are deployment settings,
not strategy rules. `HEDGY_ACCOUNTS_CONFIG` can select a different JSON file.

```sh
trading/.venv/bin/python3 trading/strategies/portfolio_watch/sweep.py \
  --no-quotes --positions-dir trading/positions
trading/.venv/bin/python3 trading/strategies/portfolio_watch/rebalance.py \
  --no-quotes --positions-dir trading/positions --target 5000 \
  --ca-rate 0 --fed-rate 0.15
```

The rebalancer also has documented NIIT and short-term rate assumptions in
`strategies/portfolio_watch/rules.py`; adjust those when appropriate. Blank cost
basis is surfaced for review and excluded from tax calculations.

Original Schwab `*-Positions-YYYY-MM-DD-HHMMSS.csv` exports remain supported without
conversion. Their account suffix is the alias used for configuration. `--no-quotes`
uses only CSV prices and never authenticates a brokerage client. Without that flag,
the tools use the optional Schwab quote integration.

`--state-dir` selects a separate report directory. Keep real reports private.
The bundled `positions/demo.csv` contains synthetic holdings and no credentials.
