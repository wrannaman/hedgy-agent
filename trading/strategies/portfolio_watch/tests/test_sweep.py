import tempfile
import unittest
from datetime import date
from pathlib import Path

from strategies.portfolio_watch import sweep


CSV = '''"Positions for account Example personal ...102 as of 10:05 AM ET, 2026/05/21"

"Symbol","Description","Qty (Quantity)","Price","Price Chng % (Price Change %)","Price Chng $ (Price Change $)","Mkt Val (Market Value)","Day Chng % (Day Change %)","Day Chng $ (Day Change $)","Cost Basis","Gain % (Gain/Loss %)","Gain $ (Gain/Loss $)","Ratings","Reinvest?","Reinvest Capital Gains?","% of Acct (% of Account)","Asset Type",
"AMZN","AMAZON.COM INC","100","260.00","-0.89%","-2.37","$26,000.00","-0.89%","-$237.00","$8,000.00","210.27%","$18,000.00","C","Yes","N/A","23.61%","Equity",
"VERI","VERITONE INC","2,000","2.00","5.92%","0.116","$4,000.00","5.92%","$273.30","$20,000.00","-80.00%","-$16,000.00","-","Yes","N/A","4.4%","Equity",
"Cash & Cash Investments","--","--","--","--","--","$12,000.00","0%","$0.00","--","--","--","--","--","--","10.0%","Cash and Money Market",
"Positions Total","","--","--","--","--","$100,000.00","0.28%","$311.17","$60,000.00","64.85%","$40,000.00","--","--","--","--","--",
'''

OPTION_CSV = '''"Positions for account 401k ...201 as of 10:57 AM ET, 2026/06/08"

"Symbol","Description","Qty (Quantity)","Price","Price Chng % (Price Change %)","Price Chng $ (Price Change $)","Mkt Val (Market Value)","Day Chng % (Day Change %)","Day Chng $ (Day Change $)","Cost Basis","Gain % (Gain/Loss %)","Gain $ (Gain/Loss $)","Ratings","Reinvest?","Reinvest Capital Gains?","% of Acct (% of Account)","Asset Type",
"MU 06/26/2026 565.00 P","PUT MICRON TECHNOLOGY IN$565 EXP 06/26/26","-1","4.45","-37.43%","-2.6622","-$445.00","37.43%","$266.22","-$1,200.00","64.21%","$755.00","-","N/A","N/A","-","Option",
"Cash & Cash Investments","--","--","--","--","--","$90,000.00","13.63%","$10,853.72","--","--","--","--","--","--","57.73%","Cash and Money Market",
"Positions Total","","--","--","--","--","$89,555.00","8.04%","$12,568.21","$30,000.00","116.41%","$35,000.00","--","--","--","--","--",
'''

ROTH_VGT_CSV = '''"Positions for account roth ...301 as of 10:57 AM ET, 2026/06/08"

"Symbol","Description","Qty (Quantity)","Price","Price Chng % (Price Change %)","Price Chng $ (Price Change $)","Mkt Val (Market Value)","Day Chng % (Day Change %)","Day Chng $ (Day Change $)","Cost Basis","Gain % (Gain/Loss %)","Gain $ (Gain/Loss $)","Ratings","Reinvest?","Reinvest Capital Gains?","% of Acct (% of Account)","Asset Type",
"VGT","VANGUARD INFORMATION TECHNOLOGY INDEX FUND ETF SHARES","100","120.00","0.4%","0.4","$12,000.00","0.4%","$45.00","$4,000.00","200%","$8,000.00","--","Yes","N/A","100%","ETFs & Closed End Funds",
"Positions Total","","--","--","--","--","$12,000.00","0%","$0.00","$4,000.00","--","$8,000.00","--","--","--","--","--",
'''

TAXABLE_CASH_CSV = '''"Positions for account Example taxable ...101 as of 10:57 AM ET, 2026/06/08"

"Symbol","Description","Qty (Quantity)","Price","Price Chng % (Price Change %)","Price Chng $ (Price Change $)","Mkt Val (Market Value)","Day Chng % (Day Change %)","Day Chng $ (Day Change $)","Cost Basis","Gain % (Gain/Loss %)","Gain $ (Gain/Loss $)","Ratings","Reinvest?","Reinvest Capital Gains?","% of Acct (% of Account)","Asset Type",
"Cash & Cash Investments","--","--","--","--","--","$250,000.00","0%","$0.00","--","--","--","--","--","--","100%","Cash and Money Market",
"Positions Total","","--","--","--","--","$250,000.00","0%","$0.00","--","--","--","--","--","--","--","--",
'''

TAXABLE_VGT_CSV = '''"Positions for account Example taxable ...101 as of 10:57 AM ET, 2026/06/08"

"Symbol","Description","Qty (Quantity)","Price","Price Chng % (Price Change %)","Price Chng $ (Price Change $)","Mkt Val (Market Value)","Day Chng % (Day Change %)","Day Chng $ (Day Change $)","Cost Basis","Gain % (Gain/Loss %)","Gain $ (Gain/Loss $)","Ratings","Reinvest?","Reinvest Capital Gains?","% of Acct (% of Account)","Asset Type",
"VGT","VANGUARD INFORMATION TECHNOLOGY INDEX FUND ETF SHARES","750","120.00","0.4%","0.4","$90,000.00","0.4%","$360.00","$30,000.00","200%","$60,000.00","--","Yes","N/A","9%","ETFs & Closed End Funds",
"Cash & Cash Investments","--","--","--","--","--","$898,000.00","0%","$0.00","--","--","--","--","--","--","91%","Cash and Money Market",
"Positions Total","","--","--","--","--","$988,000.00","0%","$0.00","$30,000.00","--","$60,000.00","--","--","--","--","--",
'''


class SweepTests(unittest.TestCase):
    def test_parse_position_file_normalizes_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Example personal-Positions-2026-05-21-100507.csv"
            path.write_text(CSV)

            account = sweep.parse_position_file(path, today=date(2026, 6, 3))

        self.assertEqual(account.account, "Example personal")
        self.assertEqual(account.account_suffix, "102")
        self.assertEqual(account.age_days, 13)
        self.assertTrue(account.stale)
        self.assertEqual(len(account.holdings), 3)
        self.assertEqual(account.cash_value, 12000.00)
        self.assertEqual(account.total_market_value, 100000.00)
        veri = next(h for h in account.holdings if h.symbol == "VERI")
        self.assertEqual(veri.quantity, 2000)
        self.assertEqual(veri.gain_pct, -80.00)
        self.assertEqual(veri.gain_dollars, -16000.00)

    def test_flags_include_loser_cash_concentration_and_big_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Example personal-Positions-2026-05-21-100507.csv"
            path.write_text(CSV)
            account = sweep.parse_position_file(path, today=date(2026, 6, 3))
            exposures = sweep.build_exposures([account])
            flags = sweep.build_flags([account], exposures)

        kinds = {flag["kind"] for flag in flags}
        self.assertIn("large_loser", kinds)
        self.assertIn("idle_cash", kinds)
        self.assertIn("bucket_concentration", kinds)
        self.assertIn("big_move", kinds)
        self.assertIn("stale_csv", kinds)
        self.assertTrue(sweep.summary_line(flags).startswith("Portfolio watch:"))

    def test_option_moves_do_not_create_generic_big_move_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "401k-Positions-2026-06-08-105729.csv"
            path.write_text(OPTION_CSV)
            account = sweep.parse_position_file(path, today=date(2026, 6, 9))
            flags = sweep.build_flags([account], sweep.build_exposures([account]))

        self.assertNotIn(
            "MU 06/26/2026 565.00 P",
            {flag.get("symbol") for flag in flags if flag["kind"] == "big_move"},
        )

    def test_summary_ignores_roth_only_bucket_concentration(self):
        with tempfile.TemporaryDirectory() as tmp:
            roth = Path(tmp) / "roth-Positions-2026-06-08-105736.csv"
            taxable = Path(tmp) / "Example taxable-Positions-2026-06-08-105708.csv"
            roth.write_text(ROTH_VGT_CSV)
            taxable.write_text(TAXABLE_CASH_CSV)
            accounts = [sweep.parse_position_file(roth), sweep.parse_position_file(taxable)]
            flags = sweep.build_flags(accounts, sweep.build_exposures(accounts))

        self.assertIn("bucket_concentration", {flag["kind"] for flag in flags})
        summary = sweep.summary_line(flags)
        self.assertNotIn("VGT is 100.0% of the Roth", summary)

    def test_stale_caveat_survives_higher_priority_flags(self):
        """A stale export must never be outranked out of the Slack line.

        High-priority attention items must not hide a warning that the snapshot
        dates are stale. Live price enrichment does not refresh holding quantities,
        cash, or cost basis.
        """
        attention = {"severity": "attention", "kind": "big_move",
                     "message": "SHOP moved +7.7% today in Example taxable"}
        stale = [{"severity": "warning", "kind": "stale_csv", "age_days": 106,
                  "file_date": "2026-06-08",
                  "message": f"{name} CSV is 106 days old; caveat recommendations"}
                 for name in ("401k", "Example taxable", "Example personal", "roth")]

        summary = sweep.summary_line([attention] + stale)

        self.assertIn("STALE DATA", summary)
        self.assertIn("106d old", summary)
        self.assertIn("4 position CSVs", summary)
        self.assertIn("2026-06-08", summary)
        # the caveat leads, so it is read before any number it qualifies
        self.assertLess(summary.index("STALE DATA"), summary.index("SHOP"))
        # and it does not cost the real flag its slot
        self.assertIn("SHOP moved +7.7%", summary)

    def test_summary_says_nothing_stale_when_exports_are_current(self):
        fresh = {"severity": "attention", "kind": "big_move",
                 "message": "SHOP moved +7.7% today in Example taxable"}

        summary = sweep.summary_line([fresh])

        self.assertNotIn("STALE", summary)
        self.assertTrue(summary.startswith("Portfolio watch: SHOP"))

    def test_quiet_book_with_stale_exports_never_claims_latest(self):
        """The quiet-day line used to say "from latest CSVs" over a 106-day export."""
        stale = [{"severity": "warning", "kind": "stale_csv", "age_days": 106,
                  "file_date": "2026-06-08",
                  "message": "401k CSV is 106 days old; caveat recommendations"}]

        summary = sweep.summary_line(stale)

        self.assertIn("STALE DATA", summary)
        self.assertNotIn("latest CSVs", summary)

    def test_summary_uses_whole_book_concentration(self):
        with tempfile.TemporaryDirectory() as tmp:
            roth = Path(tmp) / "roth-Positions-2026-06-08-105736.csv"
            taxable = Path(tmp) / "Example taxable-Positions-2026-06-08-105708.csv"
            roth.write_text(ROTH_VGT_CSV)
            taxable.write_text(TAXABLE_VGT_CSV)
            accounts = [sweep.parse_position_file(roth), sweep.parse_position_file(taxable)]
            flags = sweep.build_flags(accounts, sweep.build_exposures(accounts))

        summary = sweep.summary_line(flags)
        self.assertIn("VGT is 10.2% of the whole book", summary)
        self.assertNotIn("of the Roth", summary)

    def test_latest_position_files_picks_newest_per_account_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / "Example-personal-Positions-2026-03-20-110510.csv"
            new = Path(tmp) / "Example personal-Positions-2026-05-21-100507.csv"
            old.write_text(CSV)
            new.write_text(CSV)

            latest = sweep.latest_position_files(Path(tmp))

        self.assertEqual(latest["102"], new)

    def test_run_writes_stable_payload_when_no_csvs_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = sweep.run(no_quotes=True, positions_dir=tmp_path, state_dir=tmp_path / "state")

        self.assertEqual(payload["accounts"], [])
        self.assertEqual(payload["exposures_by_symbol"], {})
        self.assertEqual(payload["flags"][0]["kind"], "missing_csv")
        self.assertIn("no position CSV exports found", payload["summary"])


if __name__ == "__main__":
    unittest.main()
