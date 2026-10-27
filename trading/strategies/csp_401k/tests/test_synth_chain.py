"""The entry seam: a synthetic-but-Schwab-shaped chain must feed the REAL production
gate (best_put_from_chain) unchanged and produce a usable hit. Pure BS + a scripted
high-vol price series — no Schwab, deterministic.
"""
import math
import unittest
from datetime import date, timedelta

from strategies.csp_401k.backtest.synth_chain import build_chain
from strategies.csp_401k.backtest.volmodel import RealizedVolModel
from strategies.csp_401k.backtest.pricer import BSReconstructedPricer
from strategies.csp_401k.screener_select import best_put_from_chain


def _vol_series(n=60, start=date(2020, 1, 1), spot0=100.0, daily=0.070):
    """Deterministic high-vol path (~110% annualized; alternating ± daily returns).

    Flat-vol BS understates OTM-put premium (no put skew), so the production 2%
    premium floor only clears at high modeled vol — itself a documented limitation
    (RULES.md §12). High vol here just guarantees the real gate has a clearing hit.
    """
    closes, s = [], spot0
    for i in range(n):
        s *= math.exp(daily if i % 2 == 0 else -daily)
        closes.append((start + timedelta(days=i), round(s, 2)))
    return closes


class SynthChainTests(unittest.TestCase):
    def setUp(self):
        self.symbol = "X"
        self.series = _vol_series()
        self.asof = self.series[-1][0]
        self.spot = self.series[-1][1]
        self.vol_model = RealizedVolModel({self.symbol: self.series}, window=30, vrp_mult=1.0)
        self.pricer = BSReconstructedPricer(self.vol_model)
        self.vol = self.vol_model.vol(symbol=self.symbol, asof=self.asof)

    def test_chain_is_schwab_shaped(self):
        chain = build_chain(self.symbol, self.asof, self.spot, self.vol, self.pricer)
        self.assertEqual(chain["status"], "SUCCESS")
        self.assertEqual(chain["underlyingPrice"], self.spot)
        self.assertTrue(chain["putExpDateMap"])
        expkey = next(iter(chain["putExpDateMap"]))
        self.assertIn(":", expkey)   # "YYYY-MM-DD:dte"
        leg = next(iter(chain["putExpDateMap"][expkey].values()))[0]
        for k in ("strikePrice", "bid", "ask", "volatility", "delta", "daysToExpiration"):
            self.assertIn(k, leg)

    def test_real_gate_finds_a_hit(self):
        chain = build_chain(self.symbol, self.asof, self.spot, self.vol, self.pricer)
        hit = best_put_from_chain(chain, self.symbol)
        self.assertIsNotNone(hit)
        self.assertLess(hit["strike"], self.spot)        # OTM put
        self.assertGreater(hit["premium_pct"], 0)
        self.assertGreater(hit["delta"], 0)              # |delta|, already abs()
        self.assertTrue(28 <= hit["dte"] <= 45)


if __name__ == "__main__":
    unittest.main()
