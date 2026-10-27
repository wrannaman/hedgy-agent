"""Sweep matrix completeness + the robustness gate.

The robustness gate is the load-bearing discipline: a finding that flips across
vrp_mult columns MUST be flagged NOT robust so it can never be cited to change
rules.py (plan / RULES.md §12). Constructed cases pin both directions.
"""
import unittest
from datetime import date, timedelta

from strategies.csp_401k.backtest.sweep import run_grid
from strategies.csp_401k.backtest.report import rank_dimension


def _series(closes, start=date(2020, 1, 1)):
    return [(start + timedelta(days=i), float(c)) for i, c in enumerate(closes)]


class FakePricer:
    def __init__(self, mark):
        self._mark = mark

    def put(self, *, spot, strike, dte, asof, symbol):
        return self._mark


def _entry_factory(sym, pricer, vol_model, rs):
    """Open one position on day 0 for each symbol — deterministic, no synth chain."""
    def entry(symbol, asof, spot):
        if asof == date(2020, 1, 1):
            return {"strike": 80.0, "mid": 2.00, "dte": 40}
        return None
    return entry


class SweepMatrixTests(unittest.TestCase):
    def test_grid_matrix_is_complete(self):
        symbols = ["A", "B"]
        prices = {s: _series([100.0] * 60) for s in symbols}
        grid = {"MANAGE_DTE": [14, 21], "PROFIT_TARGET_PCT": [35, 65]}
        vrp_mults = (1.0, 1.5)
        rows = run_grid(symbols, prices, grid=grid, vrp_mults=vrp_mults,
                        pricer_factory=lambda vm: FakePricer(0.90),
                        entry_factory=_entry_factory)

        # 2×2 grid -> 4 combos, each with both vrp columns present and summarized.
        self.assertEqual(len(rows), 4)
        seen = {(r["params"]["MANAGE_DTE"], r["params"]["PROFIT_TARGET_PCT"]) for r in rows}
        self.assertEqual(seen, {(14, 35), (14, 65), (21, 35), (21, 65)})
        for r in rows:
            for vm in vrp_mults:
                self.assertIn(vm, r["by_vrp"])
                self.assertIn("n", r["by_vrp"][vm])


class RobustnessTests(unittest.TestCase):
    def test_flip_across_vrp_is_not_robust(self):
        rows = [
            {"params": {"MANAGE_DTE": 14},
             "by_vrp": {1.0: {"n": 5, "total_return_pct": 10.0},
                        1.5: {"n": 5, "total_return_pct": 2.0}}},
            {"params": {"MANAGE_DTE": 21},
             "by_vrp": {1.0: {"n": 5, "total_return_pct": 5.0},
                        1.5: {"n": 5, "total_return_pct": 8.0}}},
        ]
        rk = rank_dimension(rows, "MANAGE_DTE", (1.0, 1.5))
        self.assertFalse(rk["robust"])        # 14 wins at 1.0, 21 wins at 1.5 -> flip
        self.assertIsNone(rk["winner"])

    def test_consistent_winner_is_robust(self):
        rows = [
            {"params": {"PROFIT_TARGET_PCT": 35},
             "by_vrp": {1.0: {"n": 5, "total_return_pct": 3.0},
                        1.5: {"n": 5, "total_return_pct": 4.0}}},
            {"params": {"PROFIT_TARGET_PCT": 65},
             "by_vrp": {1.0: {"n": 5, "total_return_pct": 9.0},
                        1.5: {"n": 5, "total_return_pct": 11.0}}},
        ]
        rk = rank_dimension(rows, "PROFIT_TARGET_PCT", (1.0, 1.5))
        self.assertTrue(rk["robust"])
        self.assertEqual(rk["winner"], 65)


if __name__ == "__main__":
    unittest.main()
