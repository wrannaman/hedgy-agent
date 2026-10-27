"""Deterministic engine tests — no Schwab, no Black-Scholes.

A fake pricer returns scripted marks and a fake entry opens exactly one position, so
every realized P&L is exact and the test pins the engine's bookkeeping + the real
verdict's exit branches. The vol model / BS pricer are exercised separately
(test_synth_chain.py); here the point is the replay loop and P&L realization.
"""
import unittest
from datetime import date, timedelta
from types import SimpleNamespace

from strategies.csp_401k.backtest.engine import run_backtest


def _series(closes, start=date(2020, 1, 1)):
    """Consecutive-day [(date, close)] from a list of closes."""
    return [(start + timedelta(days=i), c) for i, c in enumerate(closes)]


class FakePricer:
    """put() returns mark(asof, spot, strike, dte) — fully scripted."""
    def __init__(self, mark):
        self._mark = mark

    def put(self, *, spot, strike, dte, asof, symbol):
        return self._mark(asof, spot, strike, dte)


def _entry_once(open_index, start, strike, credit, dte):
    """Open exactly one position on the open_index-th day; never again."""
    open_date = start + timedelta(days=open_index)

    def entry(symbol, asof, spot):
        if asof == open_date:
            return {"strike": strike, "mid": credit, "dte": dte}
        return None
    return entry


class BacktestEngineTests(unittest.TestCase):
    def test_winner_closes_at_fifty_pct_target(self):
        start = date(2020, 1, 1)
        # Underlying flat at 100, well above the 80 strike. Mark decays to 0.90 on
        # day 5 -> 55% of the 2.00 credit -> CLOSE (50% target), pnl > 0.
        prices = _series([100.0] * 20, start)
        pricer = FakePricer(lambda asof, spot, strike, dte: 0.90 if asof >= start + timedelta(days=5) else 1.80)
        entry = _entry_once(0, start, strike=80.0, credit=2.00, dte=40)
        closed = run_backtest("X", prices, pricer, entry=entry, contracts=1)

        self.assertEqual(len(closed), 1)
        t = closed[0]
        self.assertEqual(t["exit_reason"], "CLOSE")
        self.assertGreater(t["pnl"], 0)
        self.assertAlmostEqual(t["pnl"], (2.00 - 0.90) * 100)

    def test_strike_proximity_cuts_with_scripted_loss(self):
        start = date(2020, 1, 1)
        # Underlying falls onto the strike by day 4 (82 vs 80 strike -> within 5%).
        # Mark 3.50 (< 2x credit, so this is the strike-proximity branch, not the stop).
        closes = [100, 95, 90, 85, 82, 82, 82, 82]
        prices = _series([float(c) for c in closes], start)
        pricer = FakePricer(lambda asof, spot, strike, dte: 3.50)
        entry = _entry_once(0, start, strike=80.0, credit=2.00, dte=40)
        closed = run_backtest("X", prices, pricer, entry=entry, contracts=1)

        self.assertEqual(len(closed), 1)
        t = closed[0]
        self.assertEqual(t["exit_reason"], "CUT")
        self.assertEqual(t["exit_mark"], 3.50)
        self.assertAlmostEqual(t["pnl"], (2.00 - 3.50) * 100)   # realized loss matches mark
        self.assertLess(t["pnl"], 0)

    def test_untouched_path_expires_worthless_full_credit(self):
        start = date(2020, 1, 1)
        # Hold-to-expiry rules (MANAGE_DTE None, STOP None): mark never trips 50%
        # (stays at 1.50 = 25% of max), underlying stays high -> rides to expiry ->
        # intrinsic 0 -> full credit captured.
        hold_rs = SimpleNamespace(STOP_MULTIPLE=None, MANAGE_DTE=None,
                                  PROFIT_TARGET_PCT=50, STRIKE_PROXIMITY_PCT=5.0,
                                  CONTRACTS_PER_UNDERLYING=1)
        prices = _series([100.0] * 12, start)   # 11 days elapsed; dte 10 < 11 -> expiry hit
        pricer = FakePricer(lambda asof, spot, strike, dte: 1.50)
        entry = _entry_once(0, start, strike=80.0, credit=2.00, dte=10)
        closed = run_backtest("X", prices, pricer, entry=entry, contracts=1, rs=hold_rs)

        self.assertEqual(len(closed), 1)
        t = closed[0]
        self.assertEqual(t["exit_reason"], "expiry")
        self.assertEqual(t["exit_mark"], 0.0)
        self.assertAlmostEqual(t["pnl"], 2.00 * 100)            # full credit


if __name__ == "__main__":
    unittest.main()
