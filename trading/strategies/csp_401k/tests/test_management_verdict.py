import unittest

from strategies.csp_401k.decision import management_verdict


def v(**kw):
    base = dict(credit=9.30, current_mid=7.05, price=621.0, sell_strike=470.0,
                dte=21, days_in_trade=11, contracts=1)
    base.update(kw)
    return management_verdict(**base)


class ManagementVerdictTests(unittest.TestCase):
    def test_wdc_winner_at_21dte_closes_not_cuts(self):
        # The bug we fixed: mid-based P&L is +225 -> a 24%-of-max WINNER -> CLOSE.
        r = v()
        self.assertGreater(r["pnl"], 0)
        self.assertEqual(r["do"], "CLOSE")

    def test_underwater_far_otm_at_21dte_holds(self):
        # A far-OTM losing fixture at the timer is HELD after clearing the stop
        # and proximity gates. A mark change alone is not a calendar exit (§3/§4).
        r = v(current_mid=10.50)   # paid more than credit -> losing, but 32% OTM
        self.assertLess(r["pnl"], 0)
        self.assertEqual(r["do"], "HOLD")
        self.assertFalse(r["alert"])               # a HOLD never pings
        self.assertTrue(r["actions"])              # ...but it still explains itself

    def test_underwater_near_strike_at_21dte_still_cuts(self):
        # A loser that is ALSO near the strike still cuts — the proximity gate fires
        # above the timer, so the new hold-the-loser rule never shields a real threat.
        r = v(current_mid=10.50, price=485.0)      # within 5% of the 470 strike
        self.assertEqual(r["do"], "CUT")
        self.assertIn("proximity", r["actions"][0].lower())

    def test_underwater_at_21dte_cuts_when_flag_on(self):
        # The old behavior remains available via the rule knob (and is what the sweep
        # tests as the alternative): MANAGE_DTE_CUTS_LOSERS=True -> cut the loser.
        from strategies.csp_401k.backtest.sweep import RuleSet
        r = v(current_mid=10.50, rs=RuleSet(MANAGE_DTE_CUTS_LOSERS=True))
        self.assertEqual(r["do"], "CUT")

    def test_21dte_win_inside_the_spread_works_a_limit(self):
        # Synthetic spread fixture: the midpoint shows a profit but the ask would
        # realize a loss. Surface a workable limit and modeled odds rather than
        # treating either instantaneous quote as an executable closing fill.
        r = v(credit=0.30, current_mid=0.295, current_ask=0.34,
              price=13.775, sell_strike=11.0, contracts=6, dte=21, days_in_trade=7,
              delta=-0.10, rv_annual=84.1, session_left_frac=1.0)
        self.assertGreater(r["pnl"], 0)            # up at the mid...
        self.assertEqual(r["do"], "WORK")          # ...so work a limit, don't pay the ask
        self.assertTrue(r["alert"])                # the worked limit remains visible to the user
        action = r["actions"][0]
        self.assertIn("$0.29", action)             # the limit, below the 0.30 credit
        self.assertIn("%", action)                 # ...with odds attached
        self.assertNotIn("$0.34", action.split("ask")[1] if "ask" in action else "")

    def test_21dte_work_limit_never_exceeds_breakeven(self):
        # A wide quote must not produce a "limit" at or above the credit — that is not a
        # win at any fill. Mid 0.34 > credit 0.30, so the limit clamps to 0.29.
        r = v(credit=0.30, current_mid=0.34, current_ask=0.50,
              price=13.775, sell_strike=11.0, contracts=6, dte=21, days_in_trade=7,
              delta=-0.10, rv_annual=84.1, session_left_frac=1.0)
        self.assertEqual(r["do"], "HOLD")          # down at the mid -> the far-OTM hold
        r2 = v(credit=0.30, current_mid=0.299, current_ask=0.50,
               price=13.775, sell_strike=11.0, contracts=6, dte=21, days_in_trade=7,
               delta=-0.10, rv_annual=84.1, session_left_frac=1.0)
        self.assertEqual(r2["do"], "WORK")
        self.assertIn("$0.29", r2["actions"][0])

    def test_21dte_work_states_odds_are_unknown_rather_than_guessing(self):
        r = v(credit=0.30, current_mid=0.295, current_ask=0.34,
              price=13.775, sell_strike=11.0, contracts=6, dte=21, days_in_trade=7)
        self.assertEqual(r["do"], "WORK")
        self.assertTrue(r["alert"])
        self.assertIn("unknown", r["actions"][0].lower())

    def test_21dte_winner_clearing_the_spread_still_closes(self):
        # The guard must not swallow a real winner: same trade, tight 0.10/0.12 quote.
        # This is past the 50% target, so it exits on that branch — and the offer ($0.12)
        # is already through the $0.15 target, so the ticket names the payable price.
        r = v(credit=0.30, current_mid=0.11, current_ask=0.12,
              price=13.775, sell_strike=11.0, contracts=6, dte=21, days_in_trade=7)
        self.assertEqual(r["do"], "CLOSE")
        self.assertIn("limit $0.12", r["actions"][0])
        self.assertNotIn("chance", r["actions"][0])   # nothing to wait for; no odds sentence

    def test_50pct_target_with_the_ask_above_the_mark_quotes_the_mark_and_the_odds(self):
        # The mid says 50% but the offer is 3c above the 50% mark. Don't quote an ask that
        # isn't a 50% close, and don't go quiet — name the mark and the odds it trades there.
        r = v(credit=0.30, current_mid=0.15, current_ask=0.18,
              price=13.775, sell_strike=11.0, contracts=6, dte=25, days_in_trade=7,
              delta=-0.10, rv_annual=84.1, session_left_frac=1.0)
        self.assertEqual(r["do"], "CLOSE")
        self.assertIn("limit $0.15", r["actions"][0])
        self.assertIn("chance it trades there", r["actions"][0])

    def test_21dte_winner_without_an_ask_keeps_mid_behavior(self):
        # current_ask=None (the backtest's Black-Scholes marks) -> unchanged pre-fix path.
        r = v()
        self.assertEqual(r["do"], "CLOSE")

    def test_2x_stop_first_sighting_is_pending(self):
        # Changed 2026-07-07 (RULES.md §4): one 2x mark on a deep-OTM put can be a quote
        # artifact (BIS Aug-2024 spread blowout), so the first sighting alerts but holds.
        r = v(current_mid=19.0, dte=40)   # >= 2x the 9.30 credit, streak 0
        self.assertEqual(r["do"], "HOLD")
        self.assertTrue(r["alert"])
        self.assertIn("STOP PENDING", r["actions"][0])
        self.assertEqual(r["stop_streak"], 1)

    def test_2x_stop_cuts_on_confirmation(self):
        # Second consecutive run seeing the 2x mark -> the loss is real -> CUT.
        r = v(current_mid=19.0, dte=40, stop_streak=1)
        self.assertEqual(r["do"], "CUT")
        self.assertIn("Stop rule", r["actions"][0])
        self.assertEqual(r["stop_streak"], 2)

    def test_stop_streak_resets_when_mark_recovers(self):
        # Mark back under 2x on the next run -> the pending stop clears.
        r = v(current_mid=8.00, dte=40, stop_streak=1)
        self.assertEqual(r["stop_streak"], 0)
        self.assertEqual(r["do"], "HOLD")

    def test_low_vix_entry_stop_is_advisory(self):
        # Project Finance regime split (RULES.md §4): on a calm-tape entry the confirmed
        # 2x mark surfaces as an alerted judgment call, never an auto-CUT.
        r = v(current_mid=19.0, dte=40, stop_streak=1, entry_vix=14.0)
        self.assertEqual(r["do"], "HOLD")
        self.assertTrue(r["alert"])
        self.assertIn("STOP ADVISORY", r["actions"][0])

    def test_high_vix_entry_stop_cuts(self):
        r = v(current_mid=19.0, dte=40, stop_streak=1, entry_vix=27.0)
        self.assertEqual(r["do"], "CUT")

    def test_unknown_entry_vix_is_conservative(self):
        # Legacy trades without entry_vix: stop stays active (treated as high-VIX).
        r = v(current_mid=19.0, dte=40, stop_streak=1, entry_vix=None)
        self.assertEqual(r["do"], "CUT")

    def test_proximity_never_deferred_by_pending_stop(self):
        # 2x mark on run 1 AND stock near the strike: proximity reads the underlying,
        # not the quote — it cuts immediately, no confirmation wait.
        r = v(current_mid=19.0, dte=40, price=485.0)   # within 5% of 470
        self.assertEqual(r["do"], "CUT")
        self.assertIn("proximity", r["actions"][0].lower())

    def test_ruleset_without_knobs_keeps_unconditional_stop(self):
        # The backtest RuleSet has no STOP_CONFIRM_RUNS / STOP_HIGH_VIX_ENTRY -> old
        # immediate behavior (modeled BS marks have no quote artifacts to guard against).
        from strategies.csp_401k.backtest.sweep import RuleSet
        r = v(current_mid=19.0, dte=40, rs=RuleSet())
        self.assertEqual(r["do"], "CUT")

    def test_strike_proximity_cuts(self):
        r = v(price=480.0, dte=40)        # within 5% of 470 strike
        self.assertEqual(r["do"], "CUT")

    def test_fifty_pct_target_closes(self):
        r = v(current_mid=4.50, dte=40)   # ~52% of max
        self.assertEqual(r["do"], "CLOSE")
        self.assertIn("target", r["actions"][0])

    def test_healthy_midlife_holds(self):
        r = v(current_mid=8.00, dte=40, price=621.0)
        self.assertEqual(r["do"], "HOLD")
        self.assertEqual(r["actions"], [])

    def test_pnl_and_pct_agree_in_sign(self):
        for mid in (4.0, 7.05, 9.30, 12.0):
            r = v(current_mid=mid)
            self.assertEqual(r["pnl"] > 0, r["pct_of_max"] > 0)


if __name__ == "__main__":
    unittest.main()
