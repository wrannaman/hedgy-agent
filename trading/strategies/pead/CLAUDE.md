# Strategy: pead

Post-earnings-announcement drift (FUND.md §2A) — long-only continuation after a
decisive positive earnings surprise, held ~one quarter.

## Scope
- **Accounts**: taxable brokerage bucket (recommendation-only — no Schwab trading
  link; FUND.md §3/§5). Never the 401k: PEAD gains are short-term/ordinary-income,
  and the taxable bucket is where FUND.md budgets that drag.
- **Instruments**: long common stock only. No options, no shorts (the short/
  negative-surprise leg is refused — see FUND.md §2B on shorting).
- **Universe**: the canonical shared list (`shared/universe.py`).
- **Data**: earnings actuals vs estimates via `shared/earnings.py` (Finnhub;
  `FINNHUB_API_KEY` in the repo-root `.schwab`). Fails soft if the key is missing.

## Rules
Numbers: `rules.py`. Reasoning + citations: `../../FUND.md`. No rules restated here.

## Run
`scan.py` -> `state/last_screen.json` (strategy `pead_long`); the morning engine
gates the candidates through `risk.evaluate` and sizes them off the fund-wide
per-trade risk cap. Recommendation-only; no order without confirmation.
