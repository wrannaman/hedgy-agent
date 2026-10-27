# Strategy: portfolio_watch

Recommendation-only cross-account portfolio watch.

## Scope
- **Accounts**: latest position CSV exports in `../../positions/`.
- **Execution**: no orders, no Schwab account actions, no trade placement.
- **Purpose**: surface portfolio context that should affect the morning decision: cash, concentration, large winners, large losers, large daily moves, stale CSVs, and overlap with 401k option candidates.

## Rules
- Read CSV exports and public quotes only.
- Treat non-401k accounts as recommendation-only. Never imply an order can be placed from this strategy.
- The 401k options strategy remains owned by `strategies/csp_401k/`.
- Do not read or print `.schwab` or `token.json`.
- If CSV data is stale, caveat the output instead of inventing freshness.

## Outputs
- `state/latest.json` — structured holdings, account freshness, exposures, flags.
- `state/latest_summary.txt` — one short line suitable for the morning brief.
