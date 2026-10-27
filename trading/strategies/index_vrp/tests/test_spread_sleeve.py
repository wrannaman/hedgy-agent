"""Gates and bookkeeping for the scaled spread sleeve (2026-08-24).

Covers the pieces the backtest promoted: the trend gate fails closed on a stale
signal (a check that can't run must say so), the ladder sizing arithmetic, the
spread-aware book parsing (an open spread is width dollars, not a phantom CSP),
and the sleeve trade-log round trip.
"""
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "strategies" / "csp_401k"))  # fund_engine imports reconcile

import fund_engine
import fund_rules as R
from strategies.index_vrp import trade_log


def _opt(symbol, short=0, long=0):
    return {"instrument": {"assetType": "OPTION", "symbol": symbol},
            "shortQuantity": short, "longQuantity": long, "marketValue": 0}


class TestTrendGate(unittest.TestCase):
    def test_risk_on_fresh_signal_opens_the_gate(self):
        t = {"timestamp": date.today().isoformat(), "regime": "risk_on"}
        self.assertIsNone(fund_engine.trend_gate_reason(t))

    def test_risk_off_rejects_new_spreads(self):
        t = {"timestamp": date.today().isoformat(), "regime": "risk_off"}
        self.assertIn("risk_off", fund_engine.trend_gate_reason(t))

    def test_stale_signal_fails_closed_and_says_so(self):
        # The gate can't run on yesterday's regime — it must reject WITH the stale
        # reason, never silently pass (the DELL-earnings lesson, LEARNINGS #9-13).
        t = {"timestamp": "2026-08-21T06:35:00", "regime": "risk_on"}
        reason = fund_engine.trend_gate_reason(t)
        self.assertIn("stale", reason)
        self.assertIn("2026-08-21", reason)

    def test_missing_signal_fails_closed(self):
        self.assertIn("fail closed", fund_engine.trend_gate_reason(None))


class TestLadderSizing(unittest.TestCase):
    def _cand(self, width=40.0, collateral=3_400, credit=6.0):
        return {"symbol": "XSP", "strategy": "put_spread", "width": width,
                "collateral": collateral, "net_credit": credit}

    def test_empty_book_sizes_one_rung(self):
        # rung = cap / rungs (~$10k); a $4k-wide spread fills it with rung//4k contracts.
        rung = R.SPREAD_DEPLOYMENT_CAP_DOLLARS / R.SPREAD_LADDER_RUNGS
        c = fund_engine.size_spread_candidate(self._cand(), 0)
        n = int(rung // 4_000)
        self.assertEqual(c["contracts"], n)
        self.assertEqual(c["total_width_dollars"], 4_000 * n)
        self.assertEqual(c["collateral"], 3_400 * n)   # scaled with contracts
        self.assertEqual(c["premium_dollars"], 600 * n)

    def test_room_smaller_than_rung_limits_entry(self):
        # Only $3k of cap room left -> floors at 1 contract; the deployment gate in
        # risk.evaluate is what rejects it if even 1 won't fit.
        c = fund_engine.size_spread_candidate(
            self._cand(), R.SPREAD_DEPLOYMENT_CAP_DOLLARS - 3_000)
        self.assertEqual(c["contracts"], 1)

    def test_non_spread_candidate_untouched(self):
        c = {"symbol": "DELL", "strategy": "cash_secured_put", "collateral": 34_000}
        self.assertEqual(fund_engine.size_spread_candidate(dict(c), 0), c)


class TestSpreadAwareBook(unittest.TestCase):
    def test_short_long_pair_becomes_width_not_collateral(self):
        # Synthetic spread fixture: locked exposure is its width, not full short-put collateral.
        holdings, locked = fund_engine.pair_put_positions([
            _opt("QQQ   260717P00672000", short=1),
            _opt("QQQ   260717P00625000", long=1),
        ])
        self.assertEqual(holdings, [{"symbol": "QQQ", "exposure": 4_700.0,
                                     "kind": "put_spread"}])
        self.assertEqual(locked, 4_700.0)

    def test_lone_short_put_still_full_collateral(self):
        holdings, locked = fund_engine.pair_put_positions(
            [_opt("DELL  260918P00340000", short=2)])
        self.assertEqual(holdings, [{"symbol": "DELL", "exposure": 68_000.0,
                                     "kind": "short_put"}])
        self.assertEqual(locked, 68_000.0)

    def test_different_expirations_do_not_pair(self):
        # A long put in another cycle is not this short put's wing.
        holdings, _ = fund_engine.pair_put_positions([
            _opt("SPY   260918P00700000", short=1),
            _opt("SPY   261016P00650000", long=1),
        ])
        kinds = sorted(h["kind"] for h in holdings)
        self.assertEqual(kinds, ["short_put"])  # long-only leg carries no exposure


class TestTradeLog(unittest.TestCase):
    def test_open_close_round_trip_and_width(self):
        with tempfile.TemporaryDirectory() as td:
            orig = trade_log.LOG_PATH
            trade_log.LOG_PATH = Path(td) / "trade_log.json"
            try:
                t = trade_log.log_trade_open("XSP", contracts=2, credit=1_200,
                                             max_loss=6_800, expiration="2026-09-25",
                                             sell_strike=740, buy_strike=720)
                self.assertEqual(t["width_dollars"], 4_000)
                self.assertEqual(trade_log.open_width_dollars(), 4_000)
                closed = trade_log.log_trade_close(t["id"], "win", 900)
                self.assertEqual(closed["status"], "closed")
                self.assertEqual(trade_log.open_width_dollars(), 0)
                # grade.py groups by strategy — every fill must carry put_spread.
                raw = json.loads(trade_log.LOG_PATH.read_text())
                self.assertEqual(raw["trades"][0]["strategy"], "put_spread")
            finally:
                trade_log.LOG_PATH = orig


if __name__ == "__main__":
    unittest.main()
