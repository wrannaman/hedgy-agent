import risk

# Today's book (2026-06-05). Active capital = free cash + active short-put collateral.
# The long ETF/share core is kind="core" (exempt). MU is the open short put (semis).
ACTIVE_CAPITAL = 79_622          # $23,122 free + $56,500 MU collateral
FREE_CASH = 23_122
HOLDINGS = [
    {"symbol": "MU",   "exposure": 56_500, "kind": "short_put"},  # open semis position
    {"symbol": "IBIT", "exposure": 25_128, "kind": "core"},        # intentional crypto core
    {"symbol": "COIN", "exposure": 1_342,  "kind": "core"},        # small long
    {"symbol": "VGT",  "exposure": 21_962, "kind": "core"},
    {"symbol": "AAPL", "exposure": 5_008,  "kind": "core"},
]
CATALYSTS = ["MSTR", "COIN", "MARA"]  # crypto names crashing today

CANDS = [
    {"symbol": "MSTR", "collateral": 8_500,  "vrp": 11},
    {"symbol": "MU",   "collateral": 63_000, "vrp": 3},
    {"symbol": "MARA", "collateral": 900,    "vrp": 14},
    {"symbol": "MRVL", "collateral": 19_000, "vrp": 1},
    {"symbol": "SMCI", "collateral": 3_200,  "vrp": -22},
    {"symbol": "COIN", "collateral": 11_500, "vrp": 7},
]


def _v(c):
    return risk.evaluate(c, HOLDINGS, ACTIVE_CAPITAL, FREE_CASH, CATALYSTS)


def test_all_six_today_are_rejected_for_real_reasons():
    for c in CANDS:
        assert _v(c)["verdict"] == "reject", (c["symbol"], _v(c))


def test_mu_rejected_on_cash_and_duplicate_not_a_bogus_5pct():
    r = _v(CANDS[1])  # MU
    joined = " ".join(r["reasons"])
    assert "cash" in joined or "defense" in joined
    assert "duplicate" in joined


def test_mrvl_rejected_on_semis_bucket_stacking():
    r = _v(CANDS[3])  # MRVL — semis bucket already maxed by MU
    assert "bucket" in " ".join(r["reasons"])


def test_clean_uncorrelated_name_passes():
    # Not held, no crowded bucket, real edge, fits cash, leaves defense buffer
    c = {"symbol": "WMT", "collateral": 9_000, "vrp": 12}
    assert _v(c)["verdict"] == "pass", _v(c)


def test_thin_edge_trims_not_rejects():
    c = {"symbol": "WMT", "collateral": 6_000, "vrp": 2}
    assert _v(c)["verdict"] == "trim", _v(c)


def test_per_trade_risk_caps_defined_risk_spreads():
    # DEFINED_RISK_PER_TRADE_PCT=6% of a $155k book = $9,300 max loss per spread
    # (2026-08-24: raised from the 3% CSP-era cap to match the backtested ladder rung).
    big = {"symbol": "QQQ", "collateral": 10_000, "vrp": 6, "strategy": "put_spread"}
    r = risk.evaluate(big, [], ACTIVE_CAPITAL, FREE_CASH, [], book_value=155_000)
    assert r["verdict"] == "reject" and "per-trade risk" in " ".join(r["reasons"]), r
    # A $5,000 trade the old 3% cap rejected now passes.
    ok = {"symbol": "QQQ", "collateral": 5_000, "vrp": 6, "strategy": "put_spread"}
    assert risk.evaluate(ok, [], ACTIVE_CAPITAL, FREE_CASH, [], book_value=155_000)["verdict"] == "pass"


def test_position_cap_blocks_when_slots_full():
    # Two open short puts = at the MAX_CONCURRENT_POSITIONS cap; a 3rd is rejected.
    full = [{"symbol": "MU", "exposure": 56_500, "kind": "short_put"},
            {"symbol": "NVDA", "exposure": 16_000, "kind": "short_put"}]
    c = {"symbol": "WMT", "collateral": 4_000, "vrp": 12, "strategy": "cash_secured_put"}
    r = risk.evaluate(c, full, ACTIVE_CAPITAL, FREE_CASH, [])
    assert r["verdict"] == "reject" and "position cap" in " ".join(r["reasons"]), r


def test_per_trade_risk_skips_cash_secured_puts():
    # CSP collateral is secured, not at-risk — the per-trade cap doesn't apply to it.
    c = {"symbol": "WMT", "collateral": 9_000, "vrp": 12, "strategy": "cash_secured_put"}
    assert risk.evaluate(c, HOLDINGS, ACTIVE_CAPITAL, FREE_CASH, [], book_value=155_000)["verdict"] == "pass"


def test_bucket_counts_core_crypto():
    # Core crypto (IBIT $25k + COIN $1.3k) is REAL correlated exposure: a big new crypto
    # short put must be rejected for stacking the bucket past the cap, even though the
    # core is exempt from the single-name flag.
    big = {"symbol": "RIOT", "collateral": 20_000, "vrp": 10}
    r = risk.evaluate(big, HOLDINGS, ACTIVE_CAPITAL, FREE_CASH, [])
    assert r["verdict"] == "reject" and "bucket" in " ".join(r["reasons"]), r
    # A small one still fits under the cap.
    small = {"symbol": "RIOT", "collateral": 4_000, "vrp": 10}
    assert risk.evaluate(small, HOLDINGS, ACTIVE_CAPITAL, FREE_CASH, [])["verdict"] == "pass"


def test_backwardation_stands_down_new_short_premium():
    # VIX/VIX3M >= 1 = backwardation: every short-premium candidate is rejected,
    # however good its own numbers — all short-vol sleeves are one correlated bet.
    c = {"symbol": "WMT", "collateral": 9_000, "vrp": 12, "strategy": "cash_secured_put"}
    r = risk.evaluate(c, HOLDINGS, ACTIVE_CAPITAL, FREE_CASH, [], vix_term_ratio=1.05)
    assert r["verdict"] == "reject" and "backwardation" in " ".join(r["reasons"]), r
    spread = {"symbol": "QQQ", "collateral": 3_200, "vrp": 6, "strategy": "put_spread"}
    r2 = risk.evaluate(spread, [], ACTIVE_CAPITAL, FREE_CASH, [], book_value=155_000,
                       vix_term_ratio=1.0)  # at the threshold counts as backwardation
    assert r2["verdict"] == "reject" and "backwardation" in " ".join(r2["reasons"]), r2


def test_contango_and_unknown_regime_do_not_gate():
    c = {"symbol": "WMT", "collateral": 9_000, "vrp": 12, "strategy": "cash_secured_put"}
    assert risk.evaluate(c, HOLDINGS, ACTIVE_CAPITAL, FREE_CASH, [],
                         vix_term_ratio=0.9)["verdict"] == "pass"
    # None must mean "regime unknown, no gate" — a quote outage can't become a stand-down.
    assert risk.evaluate(c, HOLDINGS, ACTIVE_CAPITAL, FREE_CASH, [],
                         vix_term_ratio=None)["verdict"] == "pass"


def test_backwardation_ignores_long_only_candidates():
    # A long-equity candidate (e.g. PEAD) is not short vol — the regime gate must not touch it.
    c = {"symbol": "WMT", "collateral": 9_000, "strategy": "pead_long"}
    r = risk.evaluate(c, HOLDINGS, ACTIVE_CAPITAL, FREE_CASH, [], vix_term_ratio=1.2)
    assert r["verdict"] == "pass", r


if __name__ == "__main__":
    print("=== Per-candidate verdicts (today, corrected model) ===")
    for c in CANDS:
        v = _v(c)
        print(f"  {v['symbol']:5} {v['verdict'].upper():7} — {'; '.join(v['reasons'])}")
    print("\n=== Active-book exposure (% of ${:,}) ===".format(ACTIVE_CAPITAL))
    print(" ", risk.exposure_report(HOLDINGS, ACTIVE_CAPITAL)["by_bucket_pct"])


# --- Defined-risk spread gates (2026-08-24: dollar deployment cap replaced the count
# --- cap for spreads; see fund_rules SPREAD_DEPLOYMENT_CAP_DOLLARS rationale) ---

def test_spread_not_blocked_by_csp_count_cap():
    # Two open CSPs fill the count cap, but a spread commits width dollars, not a slot.
    full = [{"symbol": "MU", "exposure": 56_500, "kind": "short_put"},
            {"symbol": "NVDA", "exposure": 16_000, "kind": "short_put"}]
    c = {"symbol": "XSP", "collateral": 3_400, "total_width_dollars": 4_000, "vrp": 12,
         "strategy": "put_spread"}
    r = risk.evaluate(c, full, ACTIVE_CAPITAL, FREE_CASH, [], book_value=160_000)
    assert "position cap" not in " ".join(r["reasons"]), r


def test_spread_deployment_cap_rejects_when_width_full():
    # Open width $2k under the cap; a $4k-width entry breaches it. Written against the
    # live cap value so a deliberate cap change doesn't break the test's point.
    cap = risk.R.SPREAD_DEPLOYMENT_CAP_DOLLARS
    book = [{"symbol": "SPY", "exposure": cap / 2, "kind": "put_spread"},
            {"symbol": "QQQ", "exposure": cap / 2 - 2_000, "kind": "put_spread"}]
    c = {"symbol": "XSP", "collateral": 3_400, "total_width_dollars": 4_000, "vrp": 12,
         "strategy": "put_spread"}
    r = risk.evaluate(c, book, ACTIVE_CAPITAL, FREE_CASH, [], book_value=160_000)
    assert r["verdict"] == "reject" and "deployment cap" in " ".join(r["reasons"]), r


def test_spread_ladder_rung_allowed_when_room():
    # One rung open, most of the cap free — a second rung fits. Same-index second
    # position is the weekly ladder, so no "duplicate" reject either.
    book = [{"symbol": "SPY", "exposure": 10_000, "kind": "put_spread"}]
    c = {"symbol": "SPY", "collateral": 8_200, "total_width_dollars": 9_600, "vrp": 12,
         "strategy": "put_spread"}
    r = risk.evaluate(c, book, ACTIVE_CAPITAL, FREE_CASH, [], book_value=160_000)
    assert r["verdict"] == "pass", r
    assert "duplicate" not in " ".join(r["reasons"]), r


def test_csp_still_blocked_at_two_slots():
    # The count cap still binds cash-secured puts exactly as before.
    full = [{"symbol": "MU", "exposure": 56_500, "kind": "short_put"},
            {"symbol": "NVDA", "exposure": 16_000, "kind": "short_put"}]
    c = {"symbol": "WMT", "collateral": 4_000, "vrp": 12, "strategy": "cash_secured_put"}
    r = risk.evaluate(c, full, ACTIVE_CAPITAL, FREE_CASH, [])
    assert r["verdict"] == "reject" and "position cap" in " ".join(r["reasons"]), r


def test_open_spreads_do_not_eat_csp_slots():
    # Two open spreads + one CSP: a new CSP sees 1/2 slots used, not 3/2.
    book = [{"symbol": "SPY", "exposure": 10_000, "kind": "put_spread"},
            {"symbol": "QQQ", "exposure": 9_000, "kind": "put_spread"},
            {"symbol": "MU", "exposure": 56_500, "kind": "short_put"}]
    c = {"symbol": "WMT", "collateral": 4_000, "vrp": 12, "strategy": "cash_secured_put"}
    r = risk.evaluate(c, book, ACTIVE_CAPITAL, FREE_CASH, [])
    assert "position cap" not in " ".join(r["reasons"]), r


def test_spread_per_trade_cap_is_defined_risk_pct():
    # DEFINED_RISK_PER_TRADE_PCT=6% of a $160k book = $9,600 max loss; $12k rejects,
    # $8.2k passes (the old 3% cap would have wrongly rejected the backtested rung).
    big = {"symbol": "QQQ", "collateral": 12_000, "total_width_dollars": 14_000,
           "vrp": 6, "strategy": "put_spread"}
    r = risk.evaluate(big, [], ACTIVE_CAPITAL, FREE_CASH, [], book_value=160_000)
    assert r["verdict"] == "reject" and "per-trade risk" in " ".join(r["reasons"]), r
    ok = {"symbol": "QQQ", "collateral": 8_200, "total_width_dollars": 9_600,
          "vrp": 6, "strategy": "put_spread"}
    assert risk.evaluate(ok, [], ACTIVE_CAPITAL, FREE_CASH, [],
                         book_value=160_000)["verdict"] == "pass"
