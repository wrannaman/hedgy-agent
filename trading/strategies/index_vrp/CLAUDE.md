# Strategy: index_vrp

Sells the **index variance-risk-premium** via **defined-risk put spreads** on broad
index ETFs (SPY/QQQ/IWM/DIA) and **$XSP** (mini-SPX index options — §1256 60/40 tax
treatment, cash-settled, no early assignment). The best-evidenced short-premium edge
(Cboe PUT Sharpe 0.65) and the diversifier the single-name sleeves lack — see
`../../FUND.md` §2A/§2C.

## Scope
- **Account**: recommendation-only today (manual execution). No order is placed without
  the account owner's explicit confirmation (repo safety floor).
- **Instruments**: defined-risk put spreads on broad-index ETFs and XSP only. Defined
  risk = the spread width, so it fits a small account where a cash-secured index put
  never would.
- **Out of scope**: single names (that's csp_401k), naked index puts, full-size SPX
  (width always breaches the per-trade risk cap at this book size — see rules.py),
  anything not a put spread.

## Rules
Canonical numbers: `rules.py`. Reasoning + citations: `../../FUND.md`. This file restates
no rules.

## Run
`scan.py` → `state/last_screen.json`; the morning engine (`../../fund_engine.py`) reads it,
applies the canonical risk gates, and ranks it into the brief.
