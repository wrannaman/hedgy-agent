"""factor — canonical numbers. Reasoning: FUND.md §2A (long-only factor tilts)."""
# The evidence-backed keepers (quality, low-vol, momentum) + value as the paired
# tilt + the benchmark. Long-only, low-turnover ETFs.
ETFS = ["MTUM", "QUAL", "USMV", "VLUE", "COWZ", "SPY"]
LOOKBACK_WEEKS = 52        # 12-month total return...
SKIP_WEEKS = 4             # ...skipping the most recent month (12-1 momentum)
TOP_N = 2                  # how many leaders to surface as the tilt
