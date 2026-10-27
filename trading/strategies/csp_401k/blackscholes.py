"""Black-Scholes for European options — pure, no I/O, no schwab.

Shared plumbing for the csp_401k sleeve: the screener uses it to value a put at
realized vol (the variance-premium EV), and the backtest pricer uses it to
reconstruct an option's price path from underlying history. One implementation so
the EV math and the backtest agree by construction.

European, continuous-comp risk-free rate, no dividends. Our puts are deep OTM and
managed before expiry, so early assignment is negligible (see RULES.md §11/§12).
"""
from __future__ import annotations

import math

# Short-dated risk-free proxy. Backtest sweeps are insensitive to this at our DTEs;
# kept as a module constant rather than a rules.py knob because it is not a strategy
# parameter. Revisit only if rates move materially.
RISK_FREE_RATE = 0.04


def _norm_cdf(x: float) -> float:
    """Standard-normal CDF via the stdlib error function. No scipy/numpy — this
    module is imported by the live screener, which runs under a venv that has no
    scientific stack. erf-based is exact, not an approximation."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _d1_d2(spot: float, strike: float, t_years: float, vol: float, r: float):
    if spot <= 0 or strike <= 0 or t_years <= 0 or vol <= 0:
        return None, None
    d1 = (math.log(spot / strike) + (r + 0.5 * vol * vol) * t_years) / (vol * math.sqrt(t_years))
    d2 = d1 - vol * math.sqrt(t_years)
    return d1, d2


def put_price(spot: float, strike: float, dte: int, vol_pct: float, r: float = RISK_FREE_RATE) -> float:
    """European put price. vol_pct is annualized vol in percent (e.g. 45.0 for 45%).

    At/with zero time or zero vol, returns intrinsic value max(strike - spot, 0).
    """
    t = max(dte, 0) / 365.0
    vol = vol_pct / 100.0
    intrinsic = max(strike - spot, 0.0)
    if t <= 0 or vol <= 0:
        return intrinsic
    d1, d2 = _d1_d2(spot, strike, t, vol, r)
    return strike * math.exp(-r * t) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def put_delta(spot: float, strike: float, dte: int, vol_pct: float, r: float = RISK_FREE_RATE) -> float:
    """Put delta in [-1, 0]. |delta| ≈ risk-neutral P(finish ITM) ≈ P(assignment)."""
    t = max(dte, 0) / 365.0
    vol = vol_pct / 100.0
    if t <= 0 or vol <= 0:
        return -1.0 if spot < strike else 0.0
    d1, _ = _d1_d2(spot, strike, t, vol, r)
    return _norm_cdf(d1) - 1.0
