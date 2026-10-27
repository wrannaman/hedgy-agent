# Strategy: morning_decision

Deterministic morning decision layer.

## Scope
- Reads outputs from `strategies/csp_401k/` and `strategies/portfolio_watch/`.
- Writes one recommended morning action for the agent to review and format.
- Recommendation-only for all non-401k accounts.

## Rules
- Never place orders.
- Never authorize non-401k trades.
- Treat `csp_401k` as the only live options strategy.
- Bad-news checks remain mandatory before any trade alert; this module can nominate a candidate, not bypass research.
- If inputs are missing or stale, write a caveated hold/no-action decision instead of guessing.

## Outputs
- `state/morning_decision.json`
- `state/morning_decision.txt`
