"""Synthetic Schwab-shaped option chain — the seam that lets the backtest test the
REAL entry gate with zero duplication.

build_chain returns a dict in the exact shape Schwab's get_option_chain returns
(putExpDateMap, underlyingPrice, per-contract bid/ask/volatility/delta/
daysToExpiration/strikePrice), so screener_select.best_put_from_chain — the actual
production entry gate — consumes it unchanged. The backtest therefore exercises the
real gate, never a copy of it.

Prices/greeks are reconstructed from the underlying close + the modeled vol via the
shared blackscholes module. A flat vol across strikes (no skew) is a documented
limitation of the free model; recorded chains carry the real skew when paid data
lands (RULES.md §12).
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blackscholes import put_delta
from rules import DTE_MIN, DTE_MAX

# bid/ask synthesized as mid ± half this fraction => a fixed spread well under the
# screener's MAX_SPREAD_PCT (15%) liquidity gate, so the synthetic chain never fails
# liquidity for a spurious reason.
_SPREAD_FRAC = 0.04


def _ladder_dtes():
    """A few expirations spanning the entry window, so best_put_from_chain has a
    real choice inside DTE_MIN..DTE_MAX."""
    mid = (DTE_MIN + DTE_MAX) // 2
    return sorted({DTE_MIN, mid, DTE_MAX})


def _ladder_strikes(spot):
    """Strikes from ~50% to ~98% of spot — deep enough OTM to cover the dynamic
    cushion gate, dense enough to find the best premium %."""
    strikes = set()
    f = 0.50
    while f <= 0.98:
        raw = spot * f
        strike = round(raw) if spot >= 50 else round(raw * 2) / 2
        if strike > 0:
            strikes.add(float(strike))
        f += 0.025
    return sorted(strikes)


def build_chain(symbol, asof, spot, vol, pricer):
    """A Schwab-shaped PUT chain for `symbol` at `asof`, priced off the modeled vol."""
    put_exp_map = {}
    for dte in _ladder_dtes():
        exp_date = (asof + timedelta(days=dte)).isoformat()
        expkey = f"{exp_date}:{dte}"
        strike_map = {}
        for strike in _ladder_strikes(spot):
            mid = pricer.put(spot=spot, strike=strike, dte=dte, asof=asof, symbol=symbol)
            if mid <= 0:
                continue
            half = mid * _SPREAD_FRAC / 2
            bid = round(mid - half, 2)
            ask = round(mid + half, 2)
            if bid <= 0 or ask <= 0:
                continue
            delta = put_delta(spot, strike, dte, vol)
            strike_map[f"{strike:.1f}"] = [{
                "strikePrice": strike,
                "bid": bid,
                "ask": ask,
                "volatility": round(vol, 2),
                "delta": round(delta, 4),
                "daysToExpiration": dte,
                "expirationDate": exp_date,
            }]
        if strike_map:
            put_exp_map[expkey] = strike_map

    return {
        "status": "SUCCESS",
        "underlyingPrice": spot,
        "putExpDateMap": put_exp_map,
    }
