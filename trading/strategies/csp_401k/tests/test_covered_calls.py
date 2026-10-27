import unittest

from strategies.csp_401k.covered_calls import EligibleHolding, summarize, verdict
from strategies.csp_401k.rules import CC_MIN_ANNUALIZED_PCT


def _candidate(**over):
    base = {
        "symbol": "IBIT", "spot": 33.6, "strike": 39, "expiration": "2026-08-07",
        "dte": 42, "contracts": 2, "mid": 0.44, "premium_dollars": 88, "otm_pct": 16,
        "annualized_pct": 11.4, "note": "",
    }
    base.update(over)
    return base


class VerdictTests(unittest.TestCase):
    def test_thin_premium_skips(self):
        # Synthetic thin-yield fixture: annualized income remains below the configured floor.
        v = verdict(_candidate())
        self.assertEqual(v["do"], "SKIP")
        self.assertIn("floor", v["reason"])

    def test_rich_premium_sells(self):
        v = verdict(_candidate(annualized_pct=CC_MIN_ANNUALIZED_PCT + 5))
        self.assertEqual(v["do"], "SELL")

    def test_boundary_at_floor_sells(self):
        v = verdict(_candidate(annualized_pct=CC_MIN_ANNUALIZED_PCT))
        self.assertEqual(v["do"], "SELL")

    def test_avoid_note_skips_regardless(self):
        v = verdict(_candidate(annualized_pct=99, note="ETF options can be thin"))
        self.assertEqual(v["do"], "SKIP")
        self.assertIn("thin", v["reason"])


class SummarizeTests(unittest.TestCase):
    def test_skip_is_committed_not_review(self):
        summary = summarize(
            [EligibleHolding("IBIT", "Bitcoin ETF", 200, 33.6, 6720, 2, 2, 15, "")],
            [_candidate()],
            no_quotes=False,
            errors=[],
        )
        self.assertIn("SKIP", summary)
        self.assertNotIn("check", summary.lower())  # no undecided "check X" language

    def test_sell_renders_order_ticket(self):
        summary = summarize(
            [EligibleHolding("IBIT", "Bitcoin ETF", 200, 33.6, 6720, 2, 2, 15, "")],
            [_candidate(annualized_pct=30)],
            no_quotes=False,
            errors=[],
        )
        self.assertIn("SELL", summary)
        self.assertIn("Sell to Open", summary)

    def test_summarize_eligibility_only(self):
        summary = summarize(
            [EligibleHolding("IBIT", "Bitcoin ETF", 575, 50, 28750, 5, 2, 15, "")],
            [],
            no_quotes=True,
            errors=[],
        )
        self.assertIn("eligible owned shares", summary)


if __name__ == "__main__":
    unittest.main()
