"""Regression tests for the trade-log/account reconciler.

Synthetic position and trade fixtures exercise never-filled and previously-live
positions without exposing any user's broker exports or transaction history.

The old check compared one positions payload against the log and called every absence a
phantom. That conflates two situations needing opposite responses:

    never in the account         -> the order never filled; fix the log, free the collateral
    was in the account, now gone -> IT CLOSED; log the close, book the P&L

These tests pin that distinction, and pin that one missing payload is not enough to
unlock collateral.
"""
import unittest

from strategies.csp_401k import reconcile as rc
from strategies.csp_401k.reconcile import (
    parse_occ_symbol,
    account_short_puts,
    reconcile,
)


def _pos(underlying, exp_yymmdd, strike, contracts):
    """A Schwab-shaped short-put position leg."""
    return {
        "instrument": {
            "assetType": "OPTION",
            "symbol": f"{underlying:<6}{exp_yymmdd}P{int(strike * 1000):08d}",
            "underlyingSymbol": underlying,
            "putCall": "PUT",
        },
        "shortQuantity": float(contracts),
        "longQuantity": 0.0,
    }


def _trade(tid, symbol, strike, exp, contracts=1):
    return {
        "id": tid, "symbol": symbol, "strategy": "cash_secured_put",
        "sell_strike": strike, "expiration": exp, "contracts": contracts,
        "status": "open",
    }


MU = _trade(3, "MU", 565.0, "2026-06-26")
SHOP = _trade(4, "SHOP", 120.0, "2026-07-17")
MARA = _trade(7, "MARA", 8.0, "2026-08-21", 9)
DELL = _trade(9, "DELL", 290.0, "2026-08-21", 2)
MARA_POS = _pos("MARA", "260821", 8.0, 9)
DELL_POS = _pos("DELL", "260821", 290.0, 2)
FRESH = {"trades": {}}


class ParseOccTests(unittest.TestCase):
    def test_put(self):
        self.assertEqual(
            parse_occ_symbol("MU    260626P00565000"),
            {"underlying": "MU", "expiration": "2026-06-26", "put_call": "PUT", "strike": 565.0},
        )

    def test_call_and_fractional_strike(self):
        self.assertEqual(parse_occ_symbol("IBIT  260529C00039500")["put_call"], "CALL")
        self.assertEqual(parse_occ_symbol("IBIT  260529C00039500")["strike"], 39.5)

    def test_not_an_option(self):
        self.assertIsNone(parse_occ_symbol("AAPL"))

    def test_parses_the_mara_symbol(self):
        """The synthetic symbol must parse and match its corresponding live-position fixture."""
        self.assertEqual(
            parse_occ_symbol("MARA  260821P00008000"),
            {"underlying": "MARA", "expiration": "2026-08-21", "put_call": "PUT", "strike": 8.0},
        )

    def test_long_put_is_not_a_short_put(self):
        long_put = dict(MARA_POS, shortQuantity=0.0, longQuantity=9.0)
        self.assertEqual(account_short_puts([long_put]), [])

    def test_call_is_not_a_short_put(self):
        call = _pos("DELL", "260821", 290.0, 2)
        call["instrument"]["putCall"] = "CALL"
        self.assertEqual(account_short_puts([call]), [])


class ClosedVsPhantomTests(unittest.TestCase):
    """The MARA bug: absence AFTER confirmation is a fill, not a phantom."""

    def test_confirmed_then_gone_is_likely_closed_not_phantom(self):
        # Day 1: MARA is live in the account.
        results, state = rc.classify([MARA], [MARA_POS], FRESH, today="2026-07-20")
        self.assertEqual(results[0]["verdict"], rc.CONFIRMED)

        # Day 2: the GTC filled overnight, so it is gone from the account.
        results, state = rc.classify([MARA], [], state, today="2026-07-21")
        self.assertEqual(results[0]["verdict"], rc.LIKELY_CLOSED)
        self.assertTrue(results[0]["ever_confirmed"])
        self.assertEqual(results[0]["last_seen"], "2026-07-20")

    def test_likely_closed_fires_on_the_first_miss(self):
        """A vanished real position is the most important thing to surface — no delay."""
        _, state = rc.classify([MARA], [MARA_POS], FRESH, today="2026-07-20")
        results, _ = rc.classify([MARA], [], state, today="2026-07-21")
        self.assertEqual(results[0]["verdict"], rc.LIKELY_CLOSED)

    def test_never_seen_becomes_phantom_only_after_repeated_misses(self):
        # The MU situation: an order that never filled, absent from the first check.
        results, state = rc.classify([MU], [], FRESH, today="2026-06-01")
        self.assertEqual(results[0]["verdict"], rc.PENDING)   # one miss is not proof
        self.assertFalse(results[0]["ever_confirmed"])

        results, _ = rc.classify([MU], [], state, today="2026-06-02")
        self.assertEqual(results[0]["verdict"], rc.PHANTOM)

    def test_a_single_bad_payload_does_not_unlock_collateral(self):
        """One anomalous positions response must not free $7,200 and let the screener
        double-size into a position that is really still open."""
        _, state = rc.classify([MARA], [MARA_POS], FRESH, today="2026-07-08")
        results, _ = rc.classify([MARA], [], state, today="2026-07-09")
        self.assertEqual(rc.collateral_locked(results), 8.0 * 100 * 9)

    def test_pending_keeps_collateral_locked(self):
        results, _ = rc.classify([MARA], [], FRESH, today="2026-07-08")
        self.assertEqual(results[0]["verdict"], rc.PENDING)
        self.assertEqual(rc.collateral_locked(results), 7200.0)

    def test_only_a_believed_phantom_releases_collateral(self):
        _, state = rc.classify([MARA], [], FRESH, today="2026-07-08")
        results, _ = rc.classify([MARA], [], state, today="2026-07-09")
        self.assertEqual(results[0]["verdict"], rc.PHANTOM)
        self.assertEqual(rc.collateral_locked(results), 0)

    def test_reappearing_position_resets_the_miss_counter(self):
        _, state = rc.classify([MARA], [], FRESH, today="2026-07-08")
        _, state = rc.classify([MARA], [MARA_POS], state, today="2026-07-09")
        results, _ = rc.classify([MARA], [], state, today="2026-07-10")
        # ever_confirmed is now set, so the next absence reads as a close.
        self.assertEqual(results[0]["verdict"], rc.LIKELY_CLOSED)
        self.assertEqual(results[0]["consecutive_misses"], 1)

    def test_rerunning_the_same_day_does_not_inflate_misses(self):
        _, state = rc.classify([MARA], [], FRESH, today="2026-07-08")
        results, _ = rc.classify([MARA], [], state, today="2026-07-08")
        self.assertEqual(results[0]["consecutive_misses"], 1)
        self.assertEqual(results[0]["verdict"], rc.PENDING)


class MixedBookTests(unittest.TestCase):
    def test_the_actual_2026_07_22_book(self):
        """Mixed synthetic book: one previously observed position disappears; another remains."""
        _, state = rc.classify([MARA, DELL], [MARA_POS, DELL_POS], FRESH, today="2026-07-20")
        results, _ = rc.classify([MARA, DELL], [DELL_POS], state, today="2026-07-22")
        by_id = {r["trade"]["id"]: r["verdict"] for r in results}
        self.assertEqual(by_id[7], rc.LIKELY_CLOSED)
        self.assertEqual(by_id[9], rc.CONFIRMED)
        # DELL's collateral stays locked; so does MARA's until the close is booked.
        self.assertEqual(rc.collateral_locked(results), 290.0 * 100 * 2 + 8.0 * 100 * 9)

    def test_confirmed_and_absent_split(self):
        positions = [
            _pos("SHOP", "260717", 120.0, 1),
            {"shortQuantity": 0.0, "longQuantity": 10, "instrument": {
                "assetType": "EQUITY", "symbol": "AAPL"}},
        ]
        results, _ = rc.classify([MU, SHOP], positions, FRESH)
        by_id = {r["trade"]["id"]: r["verdict"] for r in results}
        self.assertEqual(by_id[4], rc.CONFIRMED)     # SHOP
        self.assertEqual(by_id[3], rc.PENDING)       # MU, first miss

    def test_non_csp_trades_are_ignored(self):
        spread = dict(_trade(4, "QQQ", 672.0, "2026-07-17"), strategy="put_spread")
        results, _ = rc.classify([spread], [], FRESH)
        self.assertEqual(results, [])

    def test_classify_does_not_mutate_the_state_it_was_given(self):
        """A dry run must be able to classify without recording observations."""
        state = {"trades": {}}
        rc.classify([MARA], [MARA_POS], state, today="2026-07-20")
        self.assertEqual(state, {"trades": {}})


class LegacyApiTests(unittest.TestCase):
    """The old two-list shape still works for any caller that hasn't moved."""

    def test_confirmed_and_phantom_split(self):
        positions = [_pos("SHOP", "260717", 120.0, 1)]
        confirmed, absent = reconcile([MU, SHOP], positions)
        self.assertEqual([t["symbol"] for t in confirmed], ["SHOP"])
        self.assertEqual([t["symbol"] for t in absent], ["MU"])

    def test_empty_account_makes_everything_absent(self):
        confirmed, absent = reconcile([MU], [])
        self.assertEqual(confirmed, [])
        self.assertEqual(len(absent), 1)

    def test_long_put_is_not_a_short_put(self):
        positions = [{"shortQuantity": 0.0, "longQuantity": 1.0, "instrument": {
            "assetType": "OPTION", "symbol": "MU    260626P00565000",
            "putCall": "PUT", "underlyingSymbol": "MU"}}]
        self.assertEqual(account_short_puts(positions), [])
        confirmed, absent = reconcile([MU], positions)
        self.assertEqual(len(absent), 1)


if __name__ == "__main__":
    unittest.main()
