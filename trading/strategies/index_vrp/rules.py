"""
index_vrp — canonical numbers for the index variance-risk-premium sleeve.

Reasoning + citations: FUND.md §2A (index VRP, Cboe PUT Sharpe 0.65) and §2C. This
sleeve sells DEFINED-RISK put spreads on broad index ETFs — the best-evidenced edge,
sized to fit a small account (a cash-secured SPY put is ~$68k; a spread caps risk to
the width). Single source for this sleeve's thresholds; code imports, never hardcodes.
"""
# Broad-index ETFs + XSP (mini-SPX, 1/10th size). $XSP options are §1256 contracts:
# 60/40 long/short-term tax treatment regardless of holding period, cash-settled (no
# early assignment / pin risk) — IRS §1256, see FUND.md §5. Same S&P exposure as SPY,
# so when both clear the gates prefer the XSP spread for the tax treatment. Full $SPX
# is deliberately excluded: a ~30/13δ SPX spread's width is ~10x XSP's and would
# always breach the fund-wide per-trade risk cap (fund_rules.PER_TRADE_RISK_PCT) at
# this book size. Chain symbol verified against Schwab 2026-06-10.
UNIVERSE = ["$XSP", "SPY", "QQQ", "IWM", "DIA"]

DTE_MIN, DTE_MAX = 28, 45        # entry window (FUND.md §1)
SHORT_DELTA = 0.30              # sell ~30-delta put — the BXMD "sweet spot" (sells more
                               # premium than 16-delta while staying ~70% OTM)
LONG_DELTA = 0.13              # buy ~13-delta put to define risk (the protective wing)
MIN_CREDIT_PCT_OF_WIDTH = 12.0 # net credit must be >= this % of spread width. Rejects
                               # spreads that are mostly paying for the long leg; a healthy
                               # 30/13-delta index spread pays ~13-17% of width in low VIX,
                               # more when VIX is elevated. VRP (below) is the real edge gate.
MIN_VRP = 0.0                  # require positive variance risk premium (IV > realized vol)
MAX_SPREAD_PCT = 20.0          # per-leg bid/ask liquidity guard

# --- Management (2026-08-24, from the modeled 2008->2026 backtest: backtest.py +
# --- experiments.py in this folder; skew-swept, MEDIUM confidence — modeled BS prices) ---
PROFIT_TARGET_PCT = 75         # hold to 75% of max profit (GTC buy-to-close at 25% of the
                               # net credit, placed on fill). NOT the csp 50%: that rule
                               # exists because a naked put's tail stays open while you wait;
                               # the wing already caps this tail, and leaving at 50% donated
                               # ~$9k/yr in the sweep. No 21-DTE timer, no 2x stop, no
                               # strike-proximity exit — defined risk needs none of them.
TREND_EXIT_ON_FLIP = True      # close ALL open spreads when the trend sleeve's regime flips
                               # to risk_off (strategies/trend/state/signal.json, checked
                               # daily by fund_engine). Blocking only NEW entries left open
                               # spreads riding 2022 down: flip-exit cut the backtest's worst
                               # year from -$74k to -$39k (at $80k) for ~no return cost.
                               # Deployment/ladder caps are fund-wide: fund_rules.
                               # SPREAD_DEPLOYMENT_CAP_DOLLARS + SPREAD_LADDER_RUNGS.
