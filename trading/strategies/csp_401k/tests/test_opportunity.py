"""Opportunity-cost surfacing — the hold-vs-redeploy comparison (RULES.md §3).

These pin the SURFACING contract: a redeploy is offered only when a candidate has a real
edge (positive EV), fits the cash freed by closing the hold, and materially beats the
hold's annualized yield. It never decides to close — monitor.py only displays it.
"""
import unittest

from strategies.csp_401k.opportunity import annualized_yield_pct, best_redeploy


# held: current_mid 2.0 on a $100 strike, 30 DTE -> ~24.3%/yr, frees $10,000 collateral.
HELD = {"symbol": "AAA", "current_mid": 2.0, "strike": 100.0, "dte": 30, "contracts": 1}


def cand(symbol="BBB", mid=5.0, strike=100.0, dte=30, ev=100, collateral=10000, vrp=20,
         actionable=True):
    return {"symbol": symbol, "mid": mid, "strike": strike, "dte": dte,
            "ev_dollars": ev, "collateral": collateral, "vrp": vrp, "actionable": actionable,
            "p_assign_pct": 10.0, "premium_dollars": round(mid * 100)}


class AnnualizedYieldTests(unittest.TestCase):
    def test_zero_when_undefined(self):
        self.assertEqual(annualized_yield_pct(0, 100, 30), 0.0)
        self.assertEqual(annualized_yield_pct(2.0, 100, 0), 0.0)

    def test_known_value(self):
        # (2/100) * (365/30) * 100 ~= 24.3
        self.assertAlmostEqual(annualized_yield_pct(2.0, 100, 30), 24.33, places=1)


class BestRedeployTests(unittest.TestCase):
    def test_beating_candidate_is_surfaced(self):
        rd = best_redeploy(held=HELD, candidates=[cand(mid=5.0)], free_cash=5000,
                           beat_ratio=1.5)
        self.assertIsNotNone(rd)
        self.assertEqual(rd["symbol"], "BBB")
        self.assertGreater(rd["beats_by"], 1.5)

    def test_negative_ev_candidate_ignored(self):
        # Higher yield but no real edge (IV < RV) -> not a better home.
        rd = best_redeploy(held=HELD, candidates=[cand(mid=5.0, ev=-50)], free_cash=5000,
                           beat_ratio=1.5)
        self.assertIsNone(rd)

    def test_thin_edge_candidate_ignored(self):
        # High yield and positive EV, but VRP too thin to be actionable (RULES.md §1a) ->
        # not worth the churn; a redeploy target must itself be a real trade.
        rd = best_redeploy(held=HELD, candidates=[cand(mid=5.0, vrp=8, actionable=False)],
                           free_cash=5000, beat_ratio=1.5)
        self.assertIsNone(rd)

    def test_marginal_beat_below_ratio_ignored(self):
        # ~30.4%/yr vs ~24.3%/yr = 1.25x, under the 1.5x materiality bar.
        rd = best_redeploy(held=HELD, candidates=[cand(mid=2.5)], free_cash=5000,
                           beat_ratio=1.5)
        self.assertIsNone(rd)

    def test_same_symbol_ignored(self):
        rd = best_redeploy(held=HELD, candidates=[cand(symbol="AAA", mid=5.0)],
                           free_cash=5000, beat_ratio=1.5)
        self.assertIsNone(rd)

    def test_fit_uses_freed_collateral(self):
        # Candidate needs $12k; current free cash is only $500, but closing the hold frees
        # $10k -> budget $10.5k still short -> not surfaced.
        big = cand(mid=20.0, strike=120.0, collateral=12000)  # high yield, fits-dependent
        self.assertIsNone(best_redeploy(held=HELD, candidates=[big], free_cash=500,
                                        beat_ratio=1.5))
        # With $5k free, budget $15k covers the $12k -> surfaced.
        self.assertIsNotNone(best_redeploy(held=HELD, candidates=[big], free_cash=5000,
                                           beat_ratio=1.5))

    def test_picks_highest_yielding_qualifier(self):
        rd = best_redeploy(
            held=HELD,
            candidates=[cand(symbol="B1", mid=4.0), cand(symbol="B2", mid=6.0)],
            free_cash=5000, beat_ratio=1.5,
        )
        self.assertEqual(rd["symbol"], "B2")


if __name__ == "__main__":
    unittest.main()
