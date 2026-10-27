"""trend — canonical numbers. Reasoning: FUND.md §2A (Faber 10-month trend overlay)."""
BENCHMARK = "SPY"          # the equity-core regime proxy
SMA_WEEKS = 40             # ~10 months (Faber). Risk-on when price > SMA, else risk-off.
BALLAST = ["BIL", "DBMF", "GLD"]  # T-bills, managed futures, gold — the risk-off targets
