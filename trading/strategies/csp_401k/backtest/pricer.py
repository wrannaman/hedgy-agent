"""Pluggable option valuation — the seam that swaps modeled for recorded prices.

OptionPricer is the interface the engine depends on. BSReconstructedPricer is the
free implementation (Black-Scholes at a modeled vol). The day paid data lands, a
RecordedChainPricer implements the same .put() and drops in with NO engine change —
the identical harness reruns on real option marks. That swap is the whole reason the
valuation lives behind an interface instead of inline in the engine.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Protocol

# csp_401k dir on path so the shared, pure blackscholes module imports the same way
# the screener does (one BS implementation; EV math and backtest agree by construction).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blackscholes import put_price


class OptionPricer(Protocol):
    def put(self, *, spot: float, strike: float, dte: int, asof: date, symbol: str) -> float: ...


class BSReconstructedPricer:
    """Free pricer: Black-Scholes at a modeled vol. vol_model supplies the IV input.

    When the vol model has no estimate yet (insufficient history), the put falls back
    to intrinsic value — a deterministic, conservative mark, never a crash.
    """

    def __init__(self, vol_model):
        self.vol_model = vol_model

    def put(self, *, spot, strike, dte, asof, symbol):
        vol = self.vol_model.vol(symbol=symbol, asof=asof)
        if vol is None:
            return max(strike - spot, 0.0)
        return put_price(spot, strike, dte, vol)
