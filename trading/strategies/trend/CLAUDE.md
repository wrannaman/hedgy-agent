# Strategy: trend

Faber 10-month trend overlay on the equity core (FUND.md §2A) — risk-on above the
long trend, risk-off into ballast (T-bills/managed-futures/gold) below it. The
cheapest crash defense and the book's one uncorrelated stream.

## Scope
- Recommendation-only; a regime signal, not an order. No order without confirmation.
- Instruments: the equity-core regime call + ballast ETFs. Nothing else.

## Rules
Numbers: `rules.py`. Reasoning: `../../FUND.md`. No rules restated here.

## Run
`scan.py` -> `state/signal.json`; the morning engine reads it for the regime line.
