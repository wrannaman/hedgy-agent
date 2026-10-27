import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from strategies.morning_decision import decide


class MorningDecisionTests(unittest.TestCase):
    def test_picks_best_viable_candidate(self):
        screen = {
            "timestamp": "2026-06-03T07:00:00",
            "candidates": [
                {
                    "symbol": "SHOP",
                    "strike": 95,
                    "expiration": "2026-07-17",
                    "dte": 44,
                    "premium_dollars": 220,
                    "collateral": 9500,
                    "cushion_pct": 20,
                    "implied_move_pct": 18,
                    "vrp": 10,
                    "fits_cash": True,
                }
            ],
        }
        decision = decide.build_decision(
            screen,
            {"trades": []},
            {"accounts": [{"account": "main"}], "exposures_by_symbol": {}, "flags": []},
            now=datetime(2026, 6, 3, 8),
        )

        self.assertEqual(decision["action"], "CHECK_CANDIDATE")
        self.assertEqual(decision["best_candidate"]["symbol"], "SHOP")
        self.assertIn("catalyst check", decision["summary"])

    def test_backwardation_blocks_every_new_short_premium_candidate(self):
        # Fresh vol_regime.json saying backwardation must block the same trade the
        # risk gate would reject — decide.py can't contradict the morning brief.
        screen = {
            "timestamp": "2026-06-03T07:00:00",
            "candidates": [{
                "symbol": "SHOP", "strike": 95, "expiration": "2026-07-17", "dte": 44,
                "premium_dollars": 220, "collateral": 9500, "cushion_pct": 20,
                "implied_move_pct": 18, "vrp": 10, "fits_cash": True,
            }],
        }
        vol = {"vix_term_ratio": 1.08, "regime": "backwardation",
               "generated_at": "2026-06-03T07:30:00"}
        decision = decide.build_decision(
            screen, {"trades": []},
            {"accounts": [{"account": "main"}], "exposures_by_symbol": {}, "flags": []},
            now=datetime(2026, 6, 3, 8), vol_regime=vol,
        )
        self.assertNotEqual(decision["action"], "CHECK_CANDIDATE")
        self.assertIn("backwardation", decision["candidates"][0]["blockers"][0])
        # A stale snapshot (yesterday's panic) must NOT gate today's decision.
        stale = dict(vol, generated_at="2026-06-01T07:30:00")
        decision2 = decide.build_decision(
            screen, {"trades": []},
            {"accounts": [{"account": "main"}], "exposures_by_symbol": {}, "flags": []},
            now=datetime(2026, 6, 3, 8), vol_regime=stale,
        )
        self.assertEqual(decision2["action"], "CHECK_CANDIDATE")

    def test_blocks_duplicate_open_underlying_and_holds(self):
        screen = {
            "timestamp": "2026-06-03T07:00:00",
            "candidates": [{
                "symbol": "MU",
                "strike": 565,
                "expiration": "2026-06-26",
                "dte": 23,
                "premium_dollars": 200,
                "collateral": 56500,
                "cushion_pct": 25,
                "implied_move_pct": 20,
                "fits_cash": True,
            }],
        }
        trade_log = {"trades": [{"symbol": "MU", "status": "open"}]}

        decision = decide.build_decision(screen, trade_log, {"accounts": []}, now=datetime(2026, 6, 3, 8))

        self.assertEqual(decision["action"], "HOLD")
        self.assertIn("already have an open", decision["candidates"][0]["blockers"][0])

    def test_stale_screen_does_not_recommend_put(self):
        screen = {
            "timestamp": "2026-06-02T07:00:00",
            "candidates": [{
                "symbol": "SHOP",
                "strike": 95,
                "expiration": "2026-07-17",
                "dte": 44,
                "premium_dollars": 220,
                "collateral": 9500,
                "cushion_pct": 20,
                "implied_move_pct": 18,
                "fits_cash": True,
            }],
        }

        decision = decide.build_decision(
            screen,
            {"trades": []},
            {"accounts": [{"account": "main"}], "exposures_by_symbol": {}, "flags": []},
            now=datetime(2026, 6, 3, 8),
        )

        self.assertEqual(decision["action"], "NO_ACTION")
        self.assertEqual(decision["viable_candidate_count"], 0)
        self.assertIn("screener is 25.0 hours old", decision["caveats"])

    def test_missing_screen_timestamp_does_not_recommend_put(self):
        screen = {
            "candidates": [{
                "symbol": "SHOP",
                "strike": 95,
                "expiration": "2026-07-17",
                "dte": 44,
                "premium_dollars": 220,
                "collateral": 9500,
                "cushion_pct": 20,
                "implied_move_pct": 18,
                "fits_cash": True,
            }],
        }

        decision = decide.build_decision(
            screen,
            {"trades": []},
            {"accounts": [{"account": "main"}], "exposures_by_symbol": {}, "flags": []},
            now=datetime(2026, 6, 3, 8),
        )

        self.assertEqual(decision["action"], "NO_ACTION")
        self.assertIn("screener timestamp missing", decision["caveats"])

    def test_surfaces_portfolio_flag_when_no_trade(self):
        portfolio = {
            "accounts": [{"account": "personal"}],
            "exposures_by_symbol": {},
            "flags": [{
                "severity": "attention",
                "kind": "large_loser",
                "message": "VERI is down 81% in personal",
            }],
        }

        decision = decide.build_decision({"timestamp": "2026-06-03T07:00:00", "candidates": []}, {"trades": []}, portfolio)

        self.assertEqual(decision["action"], "PORTFOLIO_REVIEW")
        self.assertIn("VERI", decision["summary"])

    def test_catalyst_block_removes_candidate(self):
        screen = {
            "timestamp": "2026-06-03T07:00:00",
            "candidates": [{
                "symbol": "MSTR",
                "strike": 95,
                "expiration": "2026-07-17",
                "dte": 44,
                "premium_dollars": 214,
                "collateral": 9500,
                "cushion_pct": 30,
                "implied_move_pct": 26.6,
                "fits_cash": True,
            }],
        }
        catalyst = {
            "symbol": "MSTR",
            "verdict": "block",
            "summary": "blocked",
            "screen_timestamp": "2026-06-03T07:00:00",
            "generated_at": "2026-06-03T07:30:00",
        }

        decision = decide.build_decision(
            screen,
            {"trades": []},
            {"accounts": []},
            catalyst,
            now=datetime(2026, 6, 3, 8),
        )

        self.assertNotEqual(decision["action"], "CHECK_CANDIDATE")
        self.assertIn("catalyst check blocked", decision["candidates"][0]["blockers"][0])

    def test_stale_catalyst_is_ignored(self):
        screen = {
            "timestamp": "2026-06-03T07:00:00",
            "candidates": [{
                "symbol": "MSTR",
                "strike": 95,
                "expiration": "2026-07-17",
                "dte": 44,
                "premium_dollars": 214,
                "collateral": 9500,
                "cushion_pct": 30,
                "implied_move_pct": 26.6,
                "fits_cash": True,
            }],
        }
        catalyst = {
            "symbol": "MSTR",
            "verdict": "block",
            "summary": "blocked yesterday",
            "screen_timestamp": "2026-06-03T07:00:00",
            "generated_at": "2026-06-02T07:30:00",
        }

        decision = decide.build_decision(
            screen,
            {"trades": []},
            {"accounts": []},
            catalyst,
            now=datetime(2026, 6, 3, 8),
        )

        self.assertEqual(decision["action"], "CHECK_CANDIDATE")
        self.assertFalse(decision["candidates"][0]["blockers"])
        self.assertIn("catalyst check pending", decision["caveats"])

    def test_catalyst_for_different_screen_is_ignored(self):
        screen = {
            "timestamp": "2026-06-03T07:00:00",
            "candidates": [{
                "symbol": "MSTR",
                "strike": 95,
                "expiration": "2026-07-17",
                "dte": 44,
                "premium_dollars": 214,
                "collateral": 9500,
                "cushion_pct": 30,
                "implied_move_pct": 26.6,
                "fits_cash": True,
            }],
        }
        catalyst = {
            "symbol": "MSTR",
            "verdict": "block",
            "summary": "blocked for prior screen",
            "screen_timestamp": "2026-06-03T06:00:00",
            "generated_at": "2026-06-03T07:30:00",
        }

        decision = decide.build_decision(
            screen,
            {"trades": []},
            {"accounts": []},
            catalyst,
            now=datetime(2026, 6, 3, 8),
        )

        self.assertEqual(decision["action"], "CHECK_CANDIDATE")
        self.assertFalse(decision["candidates"][0]["blockers"])
        self.assertIn("catalyst check pending", decision["caveats"])

    def test_covered_call_fallback_when_no_put(self):
        covered_calls = {
            "mode": "live_chain",
            "candidates": [{
                "symbol": "IBIT",
                "strike": 60,
                "contracts": 2,
                "premium_dollars": 120,
                "otm_pct": 18,
                "actionable": True,
            }]
        }

        decision = decide.build_decision(
            {"timestamp": "2026-06-03T07:00:00", "candidates": []},
            {"trades": []},
            {"accounts": []},
            {},
            covered_calls,
        )

        self.assertEqual(decision["action"], "CHECK_COVERED_CALL")
        self.assertIn("IBIT", decision["summary"])

    def test_covered_call_fallback_requires_clean_live_scan(self):
        covered_calls = {
            "mode": "live_chain",
            "errors": ["IBIT: TimeoutError: quote timeout"],
            "candidates": [{
                "symbol": "IBIT",
                "strike": 60,
                "contracts": 2,
                "premium_dollars": 120,
                "otm_pct": 18,
                "actionable": True,
            }],
        }

        decision = decide.build_decision(
            {"timestamp": "2026-06-03T07:00:00", "candidates": []},
            {"trades": []},
            {"accounts": []},
            {},
            covered_calls,
        )

        self.assertEqual(decision["action"], "NO_ACTION")
        self.assertIsNone(decision["covered_call_candidate"])
        self.assertIn("covered call scan had errors", decision["caveats"])

    def test_applies_multiple_symbol_catalyst_results(self):
        screen = {
            "timestamp": "2026-06-03T07:00:00",
            "candidates": [
                {
                    "symbol": "COIN",
                    "strike": 125,
                    "expiration": "2026-07-17",
                    "dte": 30,
                    "premium_dollars": 180,
                    "collateral": 12500,
                    "cushion_pct": 24,
                    "implied_move_pct": 20,
                    "fits_cash": True,
                },
                {
                    "symbol": "MSTR",
                    "strike": 90,
                    "expiration": "2026-07-17",
                    "dte": 30,
                    "premium_dollars": 170,
                    "collateral": 9000,
                    "cushion_pct": 31,
                    "implied_move_pct": 24,
                    "fits_cash": True,
                },
            ],
        }
        catalyst = {
            "by_symbol": {
                "COIN": {
                    "symbol": "COIN",
                    "verdict": "caution",
                    "summary": "COIN caution",
                    "screen_timestamp": "2026-06-03T07:00:00",
                    "generated_at": "2026-06-03T07:30:00",
                },
                "MSTR": {
                    "symbol": "MSTR",
                    "verdict": "caution",
                    "summary": "MSTR caution",
                    "screen_timestamp": "2026-06-03T07:00:00",
                    "generated_at": "2026-06-03T07:35:00",
                },
            }
        }

        decision = decide.build_decision(
            screen,
            {"trades": []},
            {"accounts": []},
            catalyst,
            now=datetime(2026, 6, 3, 8),
        )

        self.assertEqual(decision["action"], "NO_ACTION")
        self.assertEqual(decision["viable_candidate_count"], 0)
        self.assertEqual(decision["candidates"][0]["penalties"], ["catalyst caution"])
        self.assertEqual(decision["candidates"][1]["penalties"], ["catalyst caution"])

    def test_run_writes_outputs_to_state_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            screen = root / "screen.json"
            trades = root / "trades.json"
            portfolio = root / "portfolio.json"
            covered = root / "covered.json"
            state = root / "state"
            screen.write_text('{"timestamp":"2026-06-03T07:00:00","candidates":[]}')
            trades.write_text('{"trades":[]}')
            portfolio.write_text('{"accounts":[],"flags":[]}')
            covered.write_text('{"candidates":[]}')

            decision = decide.run(screen, trades, portfolio, covered_calls_path=covered, state_dir=state)
            json_exists = (state / "morning_decision.json").exists()
            text_exists = (state / "morning_decision.txt").exists()

        self.assertEqual(decision["action"], "NO_ACTION")
        self.assertTrue(json_exists)
        self.assertTrue(text_exists)

    def test_standing_block_from_screener_is_not_ranked(self):
        # csp_401k RULES.md §5a/§5b. This ranker sorts on raw $/day and does NOT read
        # `actionable`, so an explicit screener-side block must survive ranking.
        # A blocked fixture must lose to a thinner clean candidate, not just score lower.
        screen = {
            "timestamp": "2026-08-03T07:00:00",
            "candidates": [
                {
                    "symbol": "SPCX", "strike": 75, "expiration": "2026-09-04", "dte": 32,
                    "premium_dollars": 212, "collateral": 7500, "cushion_pct": 30.4,
                    "implied_move_pct": 32.6, "vrp": 36.5, "fits_cash": True,
                    "actionable": False,
                    "standing_block": "standing disqualifier since 2026-07-28: Colossus 2 suit",
                },
                {
                    "symbol": "SHOP", "strike": 95, "expiration": "2026-09-04", "dte": 32,
                    "premium_dollars": 120, "collateral": 9500, "cushion_pct": 20,
                    "implied_move_pct": 18, "vrp": 10, "fits_cash": True,
                },
            ],
        }
        decision = decide.build_decision(
            screen, {"trades": []},
            {"accounts": [{"account": "main"}], "exposures_by_symbol": {}, "flags": []},
            now=datetime(2026, 8, 3, 8),
        )

        self.assertEqual(decision["best_candidate"]["symbol"], "SHOP")
        spcx = next(c for c in decision["candidates"] if c["symbol"] == "SPCX")
        self.assertTrue(any("standing risk" in b for b in spcx["blockers"]))

    def test_standing_block_alone_yields_no_trade(self):
        # Synthetic one-candidate board: its standing block must yield no trade.
        screen = {
            "timestamp": "2026-08-03T07:00:00",
            "candidates": [{
                "symbol": "SPCX", "strike": 75, "expiration": "2026-09-04", "dte": 32,
                "premium_dollars": 212, "collateral": 7500, "cushion_pct": 30.4,
                "implied_move_pct": 32.6, "vrp": 36.5, "fits_cash": True,
                "standing_block": "scheduled share-supply event inside the contract",
            }],
        }
        decision = decide.build_decision(
            screen, {"trades": []},
            {"accounts": [{"account": "main"}], "exposures_by_symbol": {}, "flags": []},
            now=datetime(2026, 8, 3, 8),
        )

        self.assertNotEqual(decision["action"], "CHECK_CANDIDATE")


if __name__ == "__main__":
    unittest.main()
