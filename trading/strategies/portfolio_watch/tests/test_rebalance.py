import json
import tempfile
import unittest
from pathlib import Path

from shared.positions import parse_position_file
from strategies.portfolio_watch import rebalance, rules


# A taxable account (...101) with a big winner (NVDA), a high-basis name (AAPL),
# a loss (HUBS), and an Incomplete-basis name (JNJ). Plus a sheltered Roth (...301).
TAXABLE_CSV = '''"Positions for account Example taxable ...101 as of 10:02 AM ET, 2026/05/21"

"Symbol","Description","Qty (Quantity)","Price","Price Chng % (Price Change %)","Price Chng $ (Price Change $)","Mkt Val (Market Value)","Day Chng % (Day Change %)","Day Chng $ (Day Change $)","Cost Basis","Gain % (Gain/Loss %)","Gain $ (Gain/Loss $)","Ratings","Reinvest?","Reinvest Capital Gains?","% of Acct (% of Account)","Asset Type",
"NVDA","NVIDIA CORP","500","220.00","-0.1%","-0.2","$110,000.00","-0.1%","-$100.00","$6,000.00","1733%","$104,000.00","B","Yes","N/A","55.0%","Equity",
"AAPL","APPLE INC","100","300.00","0.1%","0.3","$30,000.00","0.1%","$30.00","$20,000.00","50%","$10,000.00","A","Yes","N/A","15.0%","Equity",
"HUBS","HUBSPOT INC","35","200.00","-1%","-2","$7,000.00","-1%","-$70.00","$11,600.00","-39.7%","-$4,600.00","C","Yes","N/A","3.5%","Equity",
"JNJ","JOHNSON & JOHNSON","100","230.00","0.1%","0.2","$23,000.00","0.1%","$23.00","Incomplete","N/A","N/A","B","Yes","N/A","11.5%","Equity",
"Cash & Cash Investments","--","--","--","--","--","$30,000.00","0%","$0.00","--","--","--","--","--","--","15.0%","Cash and Money Market",
"Positions Total","","--","--","--","--","$200,000.00","0%","$0.00","$37,600.00","--","$109,400.00","--","--","--","--","--",
'''

ROTH_CSV = '''"Positions for account roth ...301 as of 10:06 AM ET, 2026/05/21"

"Symbol","Description","Qty (Quantity)","Price","Price Chng % (Price Change %)","Price Chng $ (Price Change $)","Mkt Val (Market Value)","Day Chng % (Day Change %)","Day Chng $ (Day Change $)","Cost Basis","Gain % (Gain/Loss %)","Gain $ (Gain/Loss $)","Ratings","Reinvest?","Reinvest Capital Gains?","% of Acct (% of Account)","Asset Type",
"VGT","VANGUARD INFO TECH ETF","100","114.00","0.4%","0.4","$11,400.00","0.4%","$45.00","$4,000.00","185%","$7,400.00","--","Yes","N/A","100%","ETFs & Closed End Funds",
"Positions Total","","--","--","--","--","$11,400.00","0%","$0.00","$4,000.00","--","$7,400.00","--","--","--","--","--",
'''


def _load():
    tmp = tempfile.mkdtemp()
    a = Path(tmp) / "Example taxable-Positions-2026-05-21-100204.csv"
    b = Path(tmp) / "roth-Positions-2026-05-21-100637.csv"
    a.write_text(TAXABLE_CSV)
    b.write_text(ROTH_CSV)
    return [parse_position_file(a), parse_position_file(b)], Path(tmp)


def _prep(accounts):
    """(exposures, bucket_totals, bucket_by_symbol) for the bucket-aware helpers."""
    exposures = rebalance.build_exposures(accounts)
    bt, bs = rebalance.build_bucket_exposures(accounts)
    return exposures, bt, bs


def _candidates(accounts, hold=None, short_term=None):
    exposures, bt, bs = _prep(accounts)
    return rebalance.build_candidates(
        accounts, exposures, bt, bs, 0.35, 0.55, hold or set(), short_term or set())


class TaxMathTests(unittest.TestCase):
    def test_sheltered_gain_is_untaxed(self):
        self.assertEqual(rebalance.tax_effect(7400, rules.TAX_FREE, 0.35), 0.0)
        self.assertEqual(rebalance.tax_effect(7400, rules.TAX_DEFERRED, 0.35), 0.0)

    def test_taxable_winner_owes_and_loser_saves(self):
        self.assertAlmostEqual(rebalance.tax_effect(10_000, rules.TAXABLE, 0.35), 3_500)
        self.assertAlmostEqual(rebalance.tax_effect(-4_600, rules.TAXABLE, 0.35), -1_610)

    def test_all_in_rate_components(self):
        self.assertAlmostEqual(rules.all_in_lt_rate(ca_rate=0.113, fed_rate=0.20), 0.351)


class CandidateTests(unittest.TestCase):
    def test_incomplete_basis_goes_to_review_not_plan(self):
        accounts, _ = _load()
        cands, unknown = _candidates(accounts)
        symbols = {c["symbol"] for c in cands}
        self.assertNotIn("JNJ", symbols)
        self.assertEqual(unknown[0]["symbol"], "JNJ")

    def test_hold_excludes_symbol(self):
        accounts, _ = _load()
        cands, _ = _candidates(accounts, hold={"NVDA"})
        self.assertNotIn("NVDA", {c["symbol"] for c in cands})

    def test_sheltered_lot_not_spendable(self):
        accounts, _ = _load()
        cands, _ = _candidates(accounts)
        vgt = next(c for c in cands if c["symbol"] == "VGT")
        self.assertFalse(vgt["spendable"])
        self.assertEqual(vgt["tax_to_exit_full"], 0.0)

    def test_candidate_carries_bucket_not_account_pct(self):
        accounts, _ = _load()
        cands, _ = _candidates(accounts)
        nvda = next(c for c in cands if c["symbol"] == "NVDA")
        self.assertEqual(nvda["bucket"], "taxable")
        # NVDA is $110k of the $200k taxable bucket (incl cash) = 55%, not a per-account figure
        self.assertAlmostEqual(nvda["bucket_pct"], 55.0, places=1)
        self.assertNotIn("account_pct", nvda)


class BucketTests(unittest.TestCase):
    def test_taxable_accounts_combine_into_one_bucket(self):
        accounts, _ = _load()
        totals, by_symbol = rebalance.build_bucket_exposures(accounts)
        self.assertIn("taxable", totals)
        self.assertIn("roth", totals)
        # VGT lives only in the Roth bucket here
        self.assertIn(("roth", "VGT"), by_symbol)
        self.assertNotIn(("taxable", "VGT"), by_symbol)

    def test_top_concentrations_includes_unknown_basis_name(self):
        accounts, _ = _load()
        totals, by_symbol = rebalance.build_bucket_exposures(accounts)
        conc = rebalance.top_concentrations(totals, by_symbol)
        # JNJ has Incomplete basis but is still a real position -> must appear
        self.assertIn("JNJ", {c["symbol"] for c in conc})
        # ranked by bucket share, NVDA (55%) is first
        self.assertEqual(conc[0]["symbol"], "NVDA")


class HarvestTests(unittest.TestCase):
    def test_harvest_excludes_sheltered_losses(self):
        accounts, _ = _load()
        cands, _ = _candidates(accounts)
        cands.append({"symbol": "ZZZ", "treatment": rules.TAX_FREE, "is_loss": True,
                      "gain": -5000, "tax_to_exit_full": 0.0})
        harvested = {h["symbol"] for h in rebalance.harvest_moves(cands)}
        self.assertIn("HUBS", harvested)
        self.assertNotIn("ZZZ", harvested)


class LadderTests(unittest.TestCase):
    def test_ladder_harvests_loss_before_taxing_winners(self):
        accounts, _ = _load()
        cands, _ = _candidates(accounts)
        ladder = rebalance.plan_ladder(cands, target=10_000)
        self.assertEqual(ladder["rungs"][0]["symbol"], "HUBS")
        self.assertEqual(ladder["rungs"][0]["kind"], "harvest_loss")
        ordered = [r["symbol"] for r in ladder["rungs"]]
        self.assertLess(ordered.index("AAPL"), ordered.index("NVDA") if "NVDA" in ordered else 99)

    def test_ladder_excludes_sheltered_from_spendable_target(self):
        accounts, _ = _load()
        cands, _ = _candidates(accounts)
        ladder = rebalance.plan_ladder(cands, target=200_000)
        self.assertNotIn("VGT", {r["symbol"] for r in ladder["rungs"]})


class TrailingStopTests(unittest.TestCase):
    def test_concentrated_winner_triggers_when_below_trailing_high(self):
        accounts, _ = _load()
        exposures, bt, bs = _prep(accounts)
        # NVDA's prior high was 270; current 220 -> ~18.5% drawdown, past the 15% stop.
        trailing = rebalance.update_trailing(accounts, {"NVDA": 270.0})
        triggers = rebalance.stop_triggers(accounts, exposures, bt, bs, trailing, 0.35, set())
        nvda = next(t for t in triggers if t["symbol"] == "NVDA")
        self.assertLessEqual(nvda["drawdown_from_high_pct"], -rules.TRAILING_STOP_PCT)
        self.assertGreater(nvda["tax_to_exit_taxable"], 0)
        self.assertEqual(nvda["bucket"], "taxable")

    def test_no_trigger_when_at_high(self):
        accounts, _ = _load()
        exposures, bt, bs = _prep(accounts)
        trailing = rebalance.update_trailing(accounts, {})  # high == current price
        triggers = rebalance.stop_triggers(accounts, exposures, bt, bs, trailing, 0.35, set())
        self.assertEqual(triggers, [])


class RunTests(unittest.TestCase):
    def test_run_writes_payload_and_trailing_state(self):
        accounts, pos_dir = _load()
        with tempfile.TemporaryDirectory() as state:
            payload = rebalance.run(
                target=10_000, no_quotes=True,
                positions_dir=pos_dir, state_dir=Path(state),
            )
            self.assertIn("cash_ladder", payload)
            self.assertIn("concentration", payload)
            self.assertTrue((Path(state) / "rebalance.json").exists())
            highs = json.loads((Path(state) / "trailing_highs.json").read_text())
            self.assertIn("NVDA", highs)


class StaleBannerTests(unittest.TestCase):
    """The plan must say its inputs are old before it names a dollar to sell.

    Regression for 2026-09-22: `stale_accounts` was computed into the payload and
    read by nothing, so a 106-day-old June book rendered a $50k cash ladder with
    named lots and named tax and no indication the holdings were four months old.
    """

    BASE = {
        "concentration": [],
        "harvests": [],
        "trailing_stops": [],
        "cash_ladder": {"target": 50_000, "raised": 50_000, "total_tax": 8_429,
                        "blended_rate": 0.169, "shortfall": 0,
                        "rungs": [{"kind": "trim_winner", "symbol": "COIN",
                                   "account": "Example personal",
                                   "sell_dollars": 2_015, "tax": 191}]},
        "free_moves": [],
        "needs_review": [],
    }

    def test_banner_precedes_the_cash_ladder(self):
        payload = dict(self.BASE, stale_accounts=["401k", "roth"],
                       stale_age_days=106, stale_as_of="2026-06-08")

        text = rebalance.build_text(payload)

        self.assertIn("STALE", text)
        self.assertIn("106 days old", text)
        self.assertIn("2026-06-08", text)
        self.assertLess(text.index("STALE"), text.index("CASH LADDER"))

    def test_no_banner_when_exports_are_current(self):
        text = rebalance.build_text(dict(self.BASE, stale_accounts=[]))

        self.assertNotIn("STALE", text)
        self.assertIn("CASH LADDER", text)

    def test_singular_wording_for_one_stale_export(self):
        payload = dict(self.BASE, stale_accounts=["401k"],
                       stale_age_days=12, stale_as_of="2026-09-10")

        text = rebalance.build_text(payload)

        self.assertIn("1 position export is 12 days old", text)


if __name__ == "__main__":
    unittest.main()
