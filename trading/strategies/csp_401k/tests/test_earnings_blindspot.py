"""What the earnings path actually does — pinned, not asserted in prose.

Synthetic chain fixtures pin the distinction between unknown earnings dates and
known dates inside the trade window. Earnings is context rather than an entry gate;
strike selection and sizing remain governed by the canonical rules. These tests
characterize those behaviors without depending on a brokerage account.
"""
import unittest
from unittest.mock import patch
from datetime import date

from strategies.csp_401k import pretrade, rules
from strategies.csp_401k.event_scanner import (
    EARNINGS_CALENDAR,
    check_earnings as scan_check_earnings,
    scan_events,
)
from strategies.csp_401k.screener_select import (
    best_put_from_chain,
    near_miss_from_chain,
    underlying_iv_and_spot,
)


# Synthetic high-volatility chain fixture; not an account record.
DELL = dict(
    spot=477.78, strike=340.0, dte=44, bid=10.45, ask=11.40,
    underlying_iv=101.9, delta=-0.119, cushion_pct=28.8, implied_move_pct=35.4,
)
DELL_EXPIRATION = "2026-09-18"
DELL_EARNINGS = "2026-08-27"     # aggregator projection, not a Dell announcement
FREE_CASH = 90_000.0


def _chain(strike, bid, ask, vol, delta, *, spot, dte, exp="2026-09-18", atm=None):
    """A minimal Schwab-shaped PUT chain: the leg under test plus an ATM leg.

    The ATM leg is what `underlying_iv_and_spot` reads to get underlying IV, and
    underlying IV is what implied move is computed from — so a chain without one
    cannot exercise the implied-move question at all.
    """
    legs = {
        f"{strike:.1f}": [{"bid": bid, "ask": ask, "volatility": vol,
                           "delta": delta, "daysToExpiration": dte}],
    }
    if atm is not None:
        legs[f"{spot:.1f}"] = [{"bid": 20.0, "ask": 20.6, "volatility": atm,
                                "delta": -0.5, "daysToExpiration": dte}]
    return {"status": "SUCCESS", "underlyingPrice": spot,
            "putExpDateMap": {f"{exp}:{dte}": legs}}


def _dell_chain():
    return _chain(DELL["strike"], DELL["bid"], DELL["ask"], 96.8, DELL["delta"],
                  spot=DELL["spot"], dte=DELL["dte"], atm=DELL["underlying_iv"])


# --- 1. the calendar is empty, so the unknown branch is the live one ---------

class CalendarIsEmptyTests(unittest.TestCase):
    def test_calendar_has_no_entries(self):
        # Deliberate (see the comment above the dict in event_scanner.py): hand-kept
        # dates went stale, so it was emptied. Every downstream test below therefore
        # describes the no-date branch, not a fixture artifact.
        self.assertEqual(EARNINGS_CALENDAR, {})

    def test_dell_has_no_entry(self):
        self.assertIsNone(EARNINGS_CALENDAR.get("DELL"))


# --- 2. pretrade: never blocks, and cannot distinguish unknown from clear ----

class PretradeEarningsTests(unittest.TestCase):
    def setUp(self):
        self.exp = date.fromisoformat(DELL_EXPIRATION)

    def test_unknown_date_passes(self):
        self.assertTrue(pretrade.check_earnings("DELL", self.exp)["pass"])

    def test_known_in_window_date_also_passes(self):
        # RULES.md §5: earnings is not a disqualifier. Even with the date on file and
        # the print 22 days inside the window, this returns pass=True.
        with_cal({"DELL": DELL_EARNINGS})(self._assert_in_window_passes)()

    def _assert_in_window_passes(self):
        r = pretrade.check_earnings("DELL", self.exp)
        self.assertTrue(r["pass"])
        self.assertIn(DELL_EARNINGS, r["message"])

    def test_known_out_of_window_date_passes(self):
        with_cal({"DELL": "2027-01-05"})(self._assert_out_of_window_passes)()

    def _assert_out_of_window_passes(self):
        r = pretrade.check_earnings("DELL", self.exp)
        self.assertTrue(r["pass"])
        self.assertIn("outside the trade window", r["message"])

    def test_no_field_separates_never_looked_from_looked_and_clear(self):
        # THE BLIND SPOT. "No date on file" and "date on file, outside the window" are
        # different English and the same machine-readable result: pass=True, and no key
        # anywhere in the dict says which one happened. A caller reading `pass` — which
        # is what run_full_checklist prints [OK] from — cannot tell them apart.
        unknown = pretrade.check_earnings("DELL", self.exp)
        checked = with_cal({"DELL": "2027-01-05"})(
            lambda: pretrade.check_earnings("DELL", self.exp))()

        self.assertEqual(unknown["pass"], checked["pass"])
        self.assertEqual(set(unknown) - {"message"}, set(checked) - {"message"})

    def test_checklist_prints_ok_for_an_unchecked_symbol(self):
        # The operator-visible consequence: the line the account owner reads says [OK].
        r = pretrade.check_earnings("DELL", self.exp)
        status = "[OK]" if r["pass"] else "[BLOCKED]"
        self.assertEqual(status, "[OK]")


# --- 3. event_scanner: unknown and clear are the SAME return value ----------

class EventScannerEarningsTests(unittest.TestCase):
    def test_unknown_returns_none(self):
        self.assertIsNone(scan_check_earnings("DELL", DELL_EXPIRATION))

    def test_out_of_window_returns_none(self):
        got = with_cal({"DELL": "2027-01-05"})(
            lambda: scan_check_earnings("DELL", DELL_EXPIRATION))()
        self.assertIsNone(got)

    def test_unknown_and_clear_are_indistinguishable(self):
        # Stronger than the pretrade case: not merely equal-in-effect, literally the
        # same value. `scan_events` does `if earnings: append`, so neither one can ever
        # reach the event list.
        unknown = scan_check_earnings("DELL", DELL_EXPIRATION)
        clear = with_cal({"DELL": "2027-01-05"})(
            lambda: scan_check_earnings("DELL", DELL_EXPIRATION))()
        self.assertIs(unknown, clear)

    @patch("strategies.csp_401k.event_scanner.date", type(
        "TradeDate", (date,), {"today": classmethod(lambda cls: cls(2026, 8, 5))}))
    def test_in_window_date_would_have_been_RED(self):
        # The counterfactual: the machinery works, it just had nothing to work on.
        # Populate the calendar and the fixture surfaces as a RED event 22 days out.
        got = with_cal({"DELL": DELL_EARNINGS})(
            lambda: scan_check_earnings("DELL", DELL_EXPIRATION))()
        self.assertIsNotNone(got)
        self.assertEqual(got["severity"], "RED")
        self.assertEqual(got["date"], DELL_EARNINGS)

    def test_fixture_scan_surfaced_no_earnings_event(self):
        # Synthetic end-to-end check with no earnings date available.
        result = scan_events("DELL", DELL_EXPIRATION)
        self.assertEqual(
            [e for e in result["events"] if "earnings" in e["event"].lower()], [])


# --- 4. implied move gates nothing (why the strike would not have moved) -----

class ImpliedMoveIsNotAGateTests(unittest.TestCase):
    def test_dell_row_had_cushion_inside_the_implied_move(self):
        # 28.8% cushion vs a 35.4% 1-SD move: the strike sits INSIDE what the market
        # priced. Under the pre-2026-07-14 expected-move gate this shape was rejected.
        self.assertLess(DELL["cushion_pct"], DELL["implied_move_pct"])

    def test_that_shape_still_clears_every_gate(self):
        best = best_put_from_chain(_dell_chain(), "DELL")
        self.assertIsNotNone(best, "the fixture must still be selectable")
        self.assertEqual(best["strike"], DELL["strike"])
        self.assertLess(best["cushion_pct"], best["implied_move_pct"])

    def test_implied_move_is_reported_not_enforced(self):
        best = best_put_from_chain(_dell_chain(), "DELL")
        # Present in the record...
        self.assertAlmostEqual(best["implied_move_pct"], DELL["implied_move_pct"], delta=0.6)
        # ...and the only cushion rule is the flat floor, which 28.8% clears easily.
        self.assertEqual(best["required_cushion_pct"], rules.MIN_CUSHION_PCT)
        self.assertGreater(best["cushion_pct"], rules.MIN_CUSHION_PCT)

    def test_underlying_iv_comes_from_the_atm_leg(self):
        iv, spot = underlying_iv_and_spot(_dell_chain())
        self.assertAlmostEqual(iv, DELL["underlying_iv"], places=1)
        self.assertAlmostEqual(spot, DELL["spot"], places=2)

    def test_deepening_the_strike_is_a_delta_decision_not_a_move_decision(self):
        # The DELL leg with ONLY its delta pushed over the ceiling. near_miss names the
        # single gate that killed it, so this can't pass for an incidental reason: the
        # answer is "delta", and no implied-move gate exists to be named instead.
        over = _chain(DELL["strike"], DELL["bid"], DELL["ask"], 96.8,
                      -(rules.MAX_DELTA + 0.05), spot=DELL["spot"], dte=DELL["dte"])
        record, gates = near_miss_from_chain(over, "DELL")
        self.assertIsNotNone(record)
        self.assertEqual(record["failed_gate"], "delta")
        self.assertEqual(set(gates), {"delta"})


# --- 5. full-deployment sizing -----------------------------------------------

class SizingTests(unittest.TestCase):
    def test_340_strike_uses_two_whole_contracts(self):
        self.assertEqual(rules.position_contracts(DELL["strike"], FREE_CASH), 2)

    def test_collateral_uses_full_cash_as_far_as_whole_contracts_allow(self):
        collateral = DELL["strike"] * 100 * rules.position_contracts(DELL["strike"], FREE_CASH)
        target = FREE_CASH * rules.POSITION_TARGET_PCT / 100
        self.assertLessEqual(collateral, target)
        self.assertLess(target - collateral, DELL["strike"] * 100)

    def test_collateral_still_fits_in_free_cash(self):
        self.assertLessEqual(DELL["strike"] * 100, FREE_CASH)


def _live_calendars():
    """Every distinct EARNINGS_CALENDAR dict currently loaded. Usually two.

    This repo imports the same module both ways: `strategies.csp_401k.event_scanner`
    (used by the tests) and a bare `event_scanner` (what pretrade.py itself does, since
    the scripts run with the strategy folder on sys.path). Python treats those as two
    unrelated modules, so there are two EARNINGS_CALENDAR dicts at different addresses,
    and patching one leaves the other empty — which is exactly how the first draft of
    these tests "proved" that a populated calendar changes nothing in pretrade. Collect
    them by identity and patch all of them.
    """
    import strategies.csp_401k.event_scanner as pkg_scanner
    from strategies.csp_401k import pretrade as pkg_pretrade

    seen, cals = set(), []
    for cal in (pkg_scanner.EARNINGS_CALENDAR, pkg_pretrade.EARNINGS_CALENDAR):
        if id(cal) not in seen:
            seen.add(id(cal))
            cals.append(cal)
    return cals


def with_cal(entries):
    """Run a callable with the earnings calendar temporarily populated."""
    def wrap(fn):
        def run(*a, **kw):
            cals = _live_calendars()
            for cal in cals:
                cal.update(entries)
            try:
                return fn(*a, **kw)
            finally:
                for cal in cals:
                    for k in entries:
                        cal.pop(k, None)
        return run
    return wrap


if __name__ == "__main__":
    unittest.main()
