"""Regression tests for the put screener's selection logic.

Anchored on the DVN 2026-06-08 bug: Schwab returned its -999 'greek not computed'
sentinel for a contract whose bid/ask were stale junk ($3.20 on a put truly worth
~$0.04), and because best_put picks the highest premium %, that phantom record was
surfaced as "best of 159". These tests pin the fix: a record without real greeks is
not a real quote and must never be chosen.
"""
import unittest

from strategies.csp_401k import rules
from strategies.csp_401k.screener_select import (
    best_put_from_chain, near_miss_from_chain, underlying_iv_and_spot, _greek_ok,
    compute_iv_ranks, IV_RANK_MIN_DAYS,
)


# Deltas for legs that are meant to CLEAR the strike gate. Derived from rules.MAX_DELTA so
# these fixtures can't silently rot into "passes because the leg was rejected" when the gate
# moves — which is exactly what happened when MAX_DELTA went 0.16 -> 0.11 on 2026-07-22.
OK_DELTA = -(rules.MAX_DELTA - 0.01)
OK_DELTA_DEEPER = -(rules.MAX_DELTA - 0.02)


def _chain(puts, spot=45.0, exp="2026-07-17", dte=39):
    """Build a minimal Schwab-shaped PUT chain from a list of leg dicts."""
    strike_map = {
        f"{p['strike']:.1f}": [{
            "bid": p["bid"],
            "ask": p["ask"],
            "volatility": p["vol"],
            "delta": p["delta"],
            "daysToExpiration": p.get("dte", dte),
        }]
        for p in puts
    }
    return {
        "status": "SUCCESS",
        "underlyingPrice": spot,
        "putExpDateMap": {f"{exp}:{dte}": strike_map},
    }


class GreekSentinelTests(unittest.TestCase):
    def test_greek_ok(self):
        self.assertTrue(_greek_ok(41.8))
        self.assertTrue(_greek_ok(0.118))
        self.assertTrue(_greek_ok(-0.118))      # put deltas are negative
        self.assertFalse(_greek_ok(-999.0))      # the sentinel
        self.assertFalse(_greek_ok(None))        # missing field

    def test_phantom_sentinel_record_is_rejected(self):
        # The trap: a deep-OTM put with -999 greeks and a phantom $3.20 bid
        # (premium 10%) next to a legit, thinner OTM put. Without the filter the
        # phantom wins on premium %; with it, the real put is chosen.
        chain = _chain([
            {"strike": 34.0, "bid": 3.20, "ask": 3.65, "vol": -999.0, "delta": -999.0},
            {"strike": 38.0, "bid": 0.80, "ask": 0.88, "vol": 42.0, "delta": OK_DELTA},
        ])
        best = best_put_from_chain(chain, "DVN")
        self.assertIsNotNone(best)
        self.assertEqual(best["strike"], 38.0)   # the real one, not the $3.20 phantom
        self.assertNotEqual(best["iv"], -999.0)
        self.assertLess(best["delta"], 1.0)

    def test_all_sentinel_chain_returns_none(self):
        chain = _chain([
            {"strike": 34.0, "bid": 3.20, "ask": 3.65, "vol": -999.0, "delta": -999.0},
        ])
        self.assertIsNone(best_put_from_chain(chain, "DVN"))

    def test_clean_chain_still_selects(self):
        # No sentinels — highest premium % among gate-clearers wins as before.
        chain = _chain([
            {"strike": 38.0, "bid": 0.80, "ask": 0.88, "vol": 42.0, "delta": OK_DELTA},
            {"strike": 36.0, "bid": 0.95, "ask": 1.05, "vol": 45.0, "delta": OK_DELTA_DEEPER},
        ])
        best = best_put_from_chain(chain, "DVN")
        self.assertIsNotNone(best)
        self.assertEqual(best["strike"], 36.0)   # 1.0/36=2.8% beats 0.84/38=2.2%


class UnderlyingIvTests(unittest.TestCase):
    """IV must be observable for every priced chain — even when no put clears the
    gates — so iv_history.jsonl accrues a dense series (the IV-rank prerequisite)."""

    def test_iv_from_chain_with_no_gate_clearing_put(self):
        # Strike too close to spot (cushion < 10%) — no candidate, but IV is real.
        chain = _chain([
            {"strike": 44.0, "bid": 1.50, "ask": 1.60, "vol": 38.5, "delta": -0.35},
        ])
        self.assertIsNone(best_put_from_chain(chain, "XYZ"))
        iv, spot = underlying_iv_and_spot(chain)
        self.assertEqual(iv, 38.5)
        self.assertEqual(spot, 45.0)

    def test_iv_skips_sentinels_and_uses_nearest_to_spot(self):
        chain = _chain([
            {"strike": 44.0, "bid": 1.50, "ask": 1.60, "vol": -999.0, "delta": -999.0},
            {"strike": 40.0, "bid": 0.60, "ask": 0.70, "vol": 41.0, "delta": -0.15},
        ])
        iv, spot = underlying_iv_and_spot(chain)
        self.assertEqual(iv, 41.0)   # nearest strike is a sentinel — skipped

    def test_unpriced_chain_returns_none(self):
        chain = _chain([
            {"strike": 34.0, "bid": 3.20, "ask": 3.65, "vol": -999.0, "delta": -999.0},
        ])
        iv, spot = underlying_iv_and_spot(chain)
        self.assertIsNone(iv)
        self.assertEqual(spot, 45.0)
        self.assertEqual(underlying_iv_and_spot({"status": "FAILED"}), (None, None))


class DiscussCushionTests(unittest.TestCase):
    """RULES.md §1b: a name whose only put is shallower than the published depth band can
    still be surfaced for DISCUSSION when the delta gate is dropped (the flat cushion
    floor always holds)."""

    # Strike 40 on spot 45 = 11.1% cushion (clears the 10% floor), premium 0.90/40 = 2.25%
    # (clears), but 0.20 delta — past the 0.16 band, so the strict gate rejects it.
    CHAIN = _chain([
        {"strike": 40.0, "bid": 0.85, "ask": 0.95, "vol": 60.0, "delta": -0.20},
    ])

    def test_strict_gate_rejects_shallow_high_iv_put(self):
        self.assertIsNone(best_put_from_chain(self.CHAIN, "META"))

    def test_relaxed_cushion_surfaces_it(self):
        best = best_put_from_chain(self.CHAIN, "META", require_delta_gate=False)
        self.assertIsNotNone(best)
        self.assertEqual(best["strike"], 40.0)
        self.assertGreaterEqual(best["cushion_pct"], 10.0)

    def test_relaxed_still_enforces_premium_and_flat_floor(self):
        # Too close (cushion < 10%) is rejected even in relaxed mode — the flat floor holds.
        shallow = _chain([{"strike": 41.5, "bid": 1.20, "ask": 1.30, "vol": 60.0, "delta": -0.30}])
        self.assertIsNone(best_put_from_chain(shallow, "META", require_delta_gate=False))


class NearMissTests(unittest.TestCase):
    """A name where no contract clears must retain its best near-miss and failing gate.

    These synthetic fixtures check that a rejected chain remains measurable.
    """

    # spot 183.77; ATM strike sets underlying_iv = 72.2 -> implied move 23.6% over 39 DTE.
    QCOM = _chain([
        {"strike": 184.0, "bid": 9.90, "ask": 10.10, "vol": 72.2, "delta": -0.50},
        {"strike": 160.0, "bid": 6.05, "ask": 6.25, "vol": 69.0, "delta": -0.228},
    ], spot=183.77)

    def test_the_name_vanishes_from_the_normal_screen(self):
        self.assertIsNone(best_put_from_chain(self.QCOM, "QCOM"))

    def test_near_miss_catches_it_and_names_the_gate(self):
        nm, counts = near_miss_from_chain(self.QCOM, "QCOM")
        self.assertIsNotNone(nm)
        self.assertEqual(nm["strike"], 160.0)
        self.assertEqual(nm["failed_gate"], "delta")
        self.assertEqual(nm["premium_pct"], 3.84)   # it PAID; the depth band killed it
        self.assertEqual(nm["cushion_pct"], 12.9)   # ...and it cleared the 10% floor
        self.assertEqual(nm["delta"], 0.228)        # past the 0.16 band, so: near-miss

    def test_a_put_failing_two_gates_is_not_a_near_miss(self):
        # Shallow AND under the premium floor — two gates away, not one. Not a near-miss:
        # this is a bad trade, not a trade a single gate deleted.
        chain = _chain([
            {"strike": 44.0, "bid": 0.20, "ask": 0.22, "vol": 60.0, "delta": -0.30},
        ], spot=45.0)
        nm, counts = near_miss_from_chain(chain, "XYZ")
        self.assertIsNone(nm)
        self.assertEqual(counts, {"cushion": 1, "delta": 1, "premium": 1})

    def test_atm_put_never_wins_the_near_miss_argmax(self):
        # The trap this logic walked into: the 184 strike on a 183.77 spot fails exactly one
        # gate (cushion) and has the FATTEST premium in the chain, so ranking near-misses by
        # premium_pct hands back the most dangerous strike available and calls it "one gate
        # away". The flat cushion floor excludes it; the genuine 12.9%-cushion put wins.
        nm, _ = near_miss_from_chain(self.QCOM, "QCOM")
        self.assertEqual(nm["strike"], 160.0)                       # not the 184
        self.assertGreaterEqual(nm["cushion_pct"], rules.MIN_CUSHION_PCT)

    def test_clean_chain_has_no_near_miss(self):
        chain = _chain([
            {"strike": 36.0, "bid": 0.95, "ask": 1.05, "vol": 45.0, "delta": -0.10},
        ])
        nm, _ = near_miss_from_chain(chain, "DVN")
        self.assertIsNone(nm)   # it cleared — it's a candidate, not a near-miss


class SkewDiagnosticTests(unittest.TestCase):
    """Record strike-versus-ATM skew separately from the ATM variance-risk premium.

    Synthetic fixtures show why substituting deep-put IV would relabel skew as edge.
    """

    def test_deep_put_records_its_skew_over_atm(self):
        chain = _chain([
            {"strike": 940.0, "bid": 66.0, "ask": 68.0, "vol": 92.4, "delta": -0.50},
            {"strike": 550.0, "bid": 13.10, "ask": 13.30, "vol": 126.2, "delta": -0.066},
        ], spot=937.0)
        best = best_put_from_chain(chain, "MU")
        self.assertIsNotNone(best)                    # MU's 550 DOES clear the gates...
        self.assertEqual(best["strike"], 550.0)
        self.assertEqual(best["underlying_iv"], 92.4)  # ...what VRP is measured against
        self.assertEqual(best["iv"], 126.2)            # ...what we'd actually be selling
        self.assertEqual(best["skew_pts"], 33.8)       # the gap, logged, gating nothing


class IvRankTests(unittest.TestCase):
    """Expanding-window IV rank (RULES.md §1a) — informational until ~60 days accrue."""

    @staticmethod
    def _rows(sym, day_ivs):
        return [{"symbol": sym, "date": d, "underlying_iv": iv} for d, iv in day_ivs]

    def test_rank_and_window(self):
        days = [(f"2026-06-{d:02d}", iv) for d, iv in
                zip(range(1, 11), [30, 32, 28, 35, 40, 38, 36, 33, 31, 37])]
        ranks = compute_iv_ranks(self._rows("XYZ", days))
        rank, n = ranks["XYZ"]
        self.assertEqual(n, 10)
        self.assertEqual(rank, 75)   # cur 37 in [28, 40] -> (37-28)/12 = 75%

    def test_intraday_duplicates_collapse_to_last_per_day(self):
        # Morning + intraday runs write multiple rows per day; only the last should count,
        # or duplicate days fatten the range and skew every rank.
        days = [(f"2026-06-{d:02d}", 30) for d in range(1, 10)]
        rows = self._rows("XYZ", days)
        rows += self._rows("XYZ", [("2026-06-10", 99), ("2026-06-10", 40)])  # last wins
        rank, n = compute_iv_ranks(rows)["XYZ"]
        self.assertEqual(n, 10)
        self.assertEqual(rank, 100)  # range [30,40] from kept rows; the 99 spike is gone

    def test_below_min_days_omitted(self):
        days = [(f"2026-06-{d:02d}", 30 + d) for d in range(1, IV_RANK_MIN_DAYS)]
        self.assertEqual(compute_iv_ranks(self._rows("XYZ", days)), {})

    def test_flat_series_ranks_50(self):
        days = [(f"2026-06-{d:02d}", 30.0) for d in range(1, 12)]
        rank, _ = compute_iv_ranks(self._rows("XYZ", days))["XYZ"]
        self.assertEqual(rank, 50.0)


if __name__ == "__main__":
    unittest.main()


class PositionContractsTests(unittest.TestCase):
    """rules.position_contracts — sizing on assignment exposure (RULES.md §7)."""

    def test_small_strike_scales_up(self):
        # MARA-shaped: fill the $91k book in whole $800 cash-secured contracts.
        self.assertEqual(rules.position_contracts(8.0, 91_000), 113)

    def test_big_strike_floors_at_one(self):
        # $91k / $16k collateral per contract = five whole contracts.
        self.assertEqual(rules.position_contracts(160.0, 91_000), 5)

    def test_mid_strike(self):
        # $30 strike: $91k / $3,000 = 30 whole contracts.
        self.assertEqual(rules.position_contracts(30.0, 91_000), 30)

    def test_bad_inputs_floor_at_one(self):
        self.assertEqual(rules.position_contracts(0, 91_000), 1)
        self.assertEqual(rules.position_contracts(8.0, None), 1)
        self.assertEqual(rules.position_contracts(None, 91_000), 1)
