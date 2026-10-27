# Strategy: factor

Long-only factor tilt (FUND.md §2A) — ranks quality/low-vol/momentum/value ETFs by
12-1 momentum and tilts toward the leaders vs SPY. Slow, low-turnover.

## Scope
- Recommendation-only; an allocation tilt, not a trade. No order without confirmation.
- Instruments: the factor ETFs in `rules.py`. Nothing else.

## Rules
Numbers: `rules.py`. Reasoning: `../../FUND.md`. No rules restated here.

## Run
`scan.py` -> `state/signal.json`; the morning engine reads it for the tilt line.
