import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from strategies.csp_401k import trade_log, wheel


def _csp(id=1, symbol="MARA", contracts=9, strike=8.0, credit=198, status="open"):
    return {
        "id": id, "opened": "2026-07-07T11:00:00", "symbol": symbol,
        "strategy": "cash_secured_put", "contracts": contracts,
        "sell_strike": strike, "buy_strike": None, "credit": credit,
        "max_loss": strike * 100 * contracts - credit, "expiration": "2026-08-21",
        "entry_vix": 16.0, "status": status, "closed": None, "result": None,
        "pnl": None, "notes": "", "journal": {}, "expiry_snapshot": None,
    }


class WheelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log_path = str(Path(self.tmp.name) / "trade_log.json")
        patcher = mock.patch.object(trade_log, "LOG_PATH", self.log_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def _write(self, trades, wheels=None):
        log = {"trades": trades, "config": {"max_consecutive_losses": 3}}
        if wheels is not None:
            log["wheels"] = wheels
        with open(self.log_path, "w") as f:
            json.dump(log, f)

    def test_assignment_closes_put_and_computes_basis(self):
        self._write([_csp()])
        w = wheel.start_cycle(1)
        # basis = 8 - 198/900
        self.assertAlmostEqual(w["cost_basis"], 8 - 198 / 900, places=4)
        self.assertEqual(w["shares"], 900)
        self.assertEqual(w["status"], "holding_shares")
        t = trade_log.load_log()["trades"][0]
        self.assertEqual(t["status"], "closed")
        self.assertEqual(t["result"], "assigned")
        self.assertEqual(t["pnl"], 198)  # option leg realized in full

    def test_assign_rejects_closed_or_missing_or_noncsp(self):
        self._write([_csp(status="closed"), dict(_csp(id=2), strategy="put_spread")])
        with self.assertRaises(ValueError):
            wheel.start_cycle(1)
        with self.assertRaises(ValueError):
            wheel.start_cycle(2)
        with self.assertRaises(ValueError):
            wheel.start_cycle(99)

    def test_min_call_strikes_only_active_cycles(self):
        self._write([_csp()])
        wheel.start_cycle(1)
        floors = wheel.min_call_strikes()
        self.assertIn("MARA", floors)
        wheel.close_cycle(1, 8.5)
        self.assertEqual(wheel.min_call_strikes(), {})

    def test_record_call_refuses_below_basis(self):
        self._write([_csp()])
        w = wheel.start_cycle(1)
        log = trade_log.load_log()
        log["trades"].append(dict(_csp(id=2), strategy="covered_call",
                                  sell_strike=w["cost_basis"] - 0.5))
        trade_log.save_log(log)
        with self.assertRaises(ValueError):
            wheel.record_call(1, 2)

    def test_full_cycle_pnl(self):
        # Assigned at $8 on $198 credit, sell a call for +$90, called away at $9.
        self._write([_csp()])
        wheel.start_cycle(1)
        log = trade_log.load_log()
        log["trades"].append(dict(_csp(id=2), strategy="covered_call", sell_strike=9.0,
                                  status="closed", pnl=90))
        trade_log.save_log(log)
        wheel.record_call(1, 2)
        w = wheel.close_cycle(1, 9.0, how="called_away")
        # 198 (put) + 90 (call) + (9-8)*900 (share leg vs strike) = 1188
        self.assertEqual(wheel.cycle_pnl(w), 1188)
        self.assertEqual(w["exit"]["share_pnl"], 900)

    def test_share_leg_vs_strike_not_basis(self):
        # Sold flat at the strike: share leg 0 — the credit is NOT counted twice.
        self._write([_csp()])
        wheel.start_cycle(1)
        w = wheel.close_cycle(1, 8.0, how="sold")
        self.assertEqual(w["exit"]["share_pnl"], 0)
        self.assertEqual(wheel.cycle_pnl(w), 198)


class CoveredCallWheelTests(unittest.TestCase):
    def test_wheel_candidate_summary_shows_basis_floor(self):
        from strategies.csp_401k.covered_calls import EligibleHolding, summarize
        candidate = {
            "symbol": "MARA", "spot": 7.2, "strike": 8.5, "expiration": "2026-09-18",
            "dte": 40, "contracts": 9, "mid": 0.30, "premium_dollars": 270,
            "otm_pct": 18.1, "annualized_pct": 38.0, "note": "", "wheel_basis": 7.78,
        }
        summary = summarize(
            [EligibleHolding("MARA", "Marathon", 900, 7.2, 6480, 9, 9, 7, "")],
            [candidate], no_quotes=False, errors=[],
        )
        self.assertIn("SELL", summary)
        self.assertIn("basis $7.78", summary)


if __name__ == "__main__":
    unittest.main()
