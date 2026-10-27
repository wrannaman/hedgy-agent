"""Pluggable vol model — the MODELED IV input the backtest cannot measure for free.

The free backtest has underlying closes but no recorded option IV. So it estimates
the vol an option would have been priced at as trailing realized vol times a
variance-risk-premium markup (vrp_mult). vrp_mult is the ASSUMPTION the sweep
stresses: a finding only earns promotion if it holds across vrp_mult ∈ {1.0,1.2,1.5}
(see plan / RULES.md §12). The markup is assumed, never claimed as measured.
"""
from __future__ import annotations

import math

TRADING_DAYS = 252  # annualization factor for daily-return vol


class RealizedVolModel:
    """vol(symbol, asof) = annualized trailing-`window` realized vol (percent) × vrp_mult.

    prices_by_symbol maps symbol -> [(date, close), ...]. The model uses only closes
    strictly up to and including asof — no lookahead. Returns None when there is not
    enough history yet (the engine skips entry on those early days).
    """

    def __init__(self, prices_by_symbol, window=30, vrp_mult=1.0):
        self.window = window
        self.vrp_mult = vrp_mult
        self._series = {
            sym: sorted(rows, key=lambda r: r[0])
            for sym, rows in prices_by_symbol.items()
        }

    def vol(self, *, symbol, asof):
        rows = self._series.get(symbol)
        if not rows:
            return None
        closes = [c for d, c in rows if d <= asof]
        if len(closes) < self.window + 1:
            return None
        window_closes = closes[-(self.window + 1):]
        rets = [
            math.log(window_closes[i] / window_closes[i - 1])
            for i in range(1, len(window_closes))
            if window_closes[i - 1] > 0 and window_closes[i] > 0
        ]
        if len(rets) < 2:
            return None
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        annualized_pct = math.sqrt(var) * math.sqrt(TRADING_DAYS) * 100
        return annualized_pct * self.vrp_mult
