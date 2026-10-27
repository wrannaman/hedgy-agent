"""Tests for the pure PEAD selection logic over canned Finnhub calendar payloads."""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from strategies.pead import scan, rules

TODAY = date(2026, 6, 10)


def row(symbol, report="2026-06-08", actual=1.10, estimate=1.00):
    return {"symbol": symbol, "date": report, "epsActual": actual, "epsEstimate": estimate}


class PeadSelectTests(unittest.TestCase):
    def test_decisive_beat_in_window_is_selected(self):
        cands = scan.select_candidates([row("NVDA", actual=1.20)], TODAY, universe=["NVDA"])
        self.assertEqual(len(cands), 1)
        c = cands[0]
        self.assertEqual(c["strategy"], "pead_long")
        self.assertEqual(c["surprise_pct"], 20.0)
        self.assertEqual(c["days_since_report"], 2)
        # Maturity date = report + HOLD_DAYS, the rec-grading horizon.
        self.assertEqual(c["expiration"], "2026-08-07")

    def test_small_beat_miss_and_pending_are_rejected(self):
        rows = [
            row("AAPL", actual=1.05),            # +5% — below MIN_SURPRISE_PCT
            row("META", actual=0.90),            # miss
            row("AMZN", actual=None),            # not reported yet
            row("MSFT", actual=1.50, estimate=0),  # uncomputable
        ]
        self.assertEqual(scan.select_candidates(
            rows, TODAY, universe=["AAPL", "META", "AMZN", "MSFT"]), [])

    def test_window_and_universe_gates(self):
        rows = [
            row("NVDA", report="2026-06-01", actual=1.50),  # 9 days old — outside window
            row("ZZZZ", actual=1.50),                       # not in universe
            row("MU", report="2026-06-10", actual=1.50),    # reported today — in
        ]
        cands = scan.select_candidates(rows, TODAY, universe=["NVDA", "MU"])
        self.assertEqual([c["symbol"] for c in cands], ["MU"])

    def test_ranked_by_surprise_and_capped(self):
        rows = [row(s, actual=1.0 + i * 0.1)
                for i, s in enumerate(["A1", "A2", "A3", "A4", "A5"], start=2)]
        cands = scan.select_candidates(rows, TODAY, universe=["A1", "A2", "A3", "A4", "A5"])
        self.assertEqual(len(cands), rules.MAX_CANDIDATES_PER_DAY)
        self.assertEqual(cands[0]["symbol"], "A5")  # biggest beat first

    def test_negative_estimate_beat(self):
        # Loss-narrower-than-expected: actual -0.10 vs -0.50 est = +80% of |est|.
        cands = scan.select_candidates(
            [row("RKLB", actual=-0.10, estimate=-0.50)], TODAY, universe=["RKLB"])
        self.assertEqual(cands[0]["surprise_pct"], 80.0)


def _ms(d):
    from datetime import datetime, timezone
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


class ReactionGateTests(unittest.TestCase):
    """Drift follows the market's reaction to the report, not the EPS line —
    the CHWY 2026-06-10 lesson (+50% beat, stock down 2%)."""

    CANDLES = [
        {"datetime": _ms(date(2026, 6, 8)), "close": 21.0},
        {"datetime": _ms(date(2026, 6, 9)), "close": 20.40},   # last close pre-report
        {"datetime": _ms(date(2026, 6, 10)), "close": 19.90},  # report day
    ]

    def test_reaction_uses_last_close_before_report(self):
        # vs 20.40 (June 9), not 21.0 or the report-day close.
        self.assertEqual(
            scan.reaction_pct(self.CANDLES, date(2026, 6, 10), 19.98), -2.1)
        self.assertEqual(
            scan.reaction_pct(self.CANDLES, date(2026, 6, 10), 21.42), 5.0)

    def test_no_pre_report_close_returns_none(self):
        self.assertIsNone(scan.reaction_pct([], date(2026, 6, 10), 20.0))
        only_after = [{"datetime": _ms(date(2026, 6, 11)), "close": 20.0}]
        self.assertIsNone(scan.reaction_pct(only_after, date(2026, 6, 10), 20.0))


if __name__ == "__main__":
    unittest.main()
