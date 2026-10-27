"""Fill-odds estimate + session clock (RULES.md §3, added 2026-08-03).

A close is a limit worked over a session rather than an immediate market order.
A nearby target must retain its estimated fill odds instead of silently disappearing.
These synthetic fixtures lock the
arithmetic and, more importantly, the monotonicities: more session left, more vol, and a
closer limit all have to raise the odds, or the number is worse than useless.
"""

from datetime import datetime, time

import pytest

from decision import fill_odds_today, session_fraction_left

# Synthetic option quote fixture for session/volatility sensitivity tests.
CLSK = dict(current_ask=0.34, limit_price=0.29, price=13.775, delta=-0.10, rv_annual=84.1)


# --- session clock ---------------------------------------------------------

def test_full_session_at_the_open():
    assert session_fraction_left(datetime(2026, 8, 3, 9, 30)) == pytest.approx(1.0)


def test_morning_cron_still_has_essentially_the_whole_day():
    # The cron runs 09:35 ET. This is the "particularly if it's the morning" case.
    assert session_fraction_left(datetime(2026, 8, 3, 9, 35)) > 0.98


def test_half_session_at_lunch():
    assert session_fraction_left(datetime(2026, 8, 3, 12, 45)) == pytest.approx(0.5, abs=0.01)


def test_almost_nothing_left_near_the_bell():
    assert session_fraction_left(datetime(2026, 8, 3, 15, 50)) < 0.03


def test_outside_the_session_gets_a_full_next_session():
    # A limit placed after hours rests for a whole session — it just isn't today's.
    assert session_fraction_left(datetime(2026, 8, 3, 6, 35)) == 1.0
    assert session_fraction_left(datetime(2026, 8, 3, 18, 0)) == 1.0
    assert session_fraction_left(None) == 1.0


def test_accepts_a_bare_time():
    assert session_fraction_left(time(12, 45)) == pytest.approx(0.5, abs=0.01)


# --- the estimate itself ---------------------------------------------------

def test_clsk_morning_limit_is_roughly_a_coin_flip():
    # 5c below the offer on a 0.10-delta put = a $0.50 move in an 84-vol $13.78 stock,
    # against a ~$0.73 daily sigma. Touch (not close) at any point in a full session.
    odds = fill_odds_today(**CLSK, session_left_frac=1.0)
    assert 0.40 < odds < 0.60


def test_same_limit_at_the_bell_is_hopeless():
    late = fill_odds_today(**CLSK, session_left_frac=0.02)
    assert late < 0.05
    assert late < fill_odds_today(**CLSK, session_left_frac=1.0)


def test_odds_rise_monotonically_with_session_left():
    seq = [fill_odds_today(**CLSK, session_left_frac=f) for f in (0.1, 0.3, 0.6, 1.0)]
    assert seq == sorted(seq)


def test_closer_limit_is_likelier():
    near = fill_odds_today(**{**CLSK, "limit_price": 0.33}, session_left_frac=1.0)
    far = fill_odds_today(**{**CLSK, "limit_price": 0.20}, session_left_frac=1.0)
    assert near > far


def test_more_vol_is_likelier():
    calm = fill_odds_today(**{**CLSK, "rv_annual": 20.0}, session_left_frac=1.0)
    wild = fill_odds_today(**{**CLSK, "rv_annual": 120.0}, session_left_frac=1.0)
    assert wild > calm


def test_deeper_delta_moves_the_option_more_per_dollar_of_stock():
    # A 0.40-delta put needs a quarter of the underlying move a 0.10-delta put does.
    thin = fill_odds_today(**{**CLSK, "delta": -0.10}, session_left_frac=1.0)
    thick = fill_odds_today(**{**CLSK, "delta": -0.40}, session_left_frac=1.0)
    assert thick > thin


def test_already_at_the_limit_is_certain():
    assert fill_odds_today(**{**CLSK, "limit_price": 0.34}, session_left_frac=1.0) == 1.0
    assert fill_odds_today(**{**CLSK, "limit_price": 0.40}, session_left_frac=0.01) == 1.0


def test_never_exceeds_one():
    # The reflection principle's factor of 2 reaches 1.0 as the move needed goes to zero,
    # so it must be capped or a near-touch reports >100%. Sweep the whole surface.
    for limit in (0.3399, 0.33, 0.30, 0.25, 0.10, 0.01):
        for frac in (0.01, 0.25, 1.0):
            odds = fill_odds_today(**{**CLSK, "limit_price": limit}, session_left_frac=frac)
            assert 0.0 <= odds <= 1.0, (limit, frac, odds)
    near = fill_odds_today(**{**CLSK, "limit_price": 0.3399}, session_left_frac=1.0)
    assert near > 0.99


def test_missing_inputs_return_none_rather_than_a_number():
    for missing in ("delta", "rv_annual", "price", "current_ask"):
        args = {**CLSK, missing: None}
        assert fill_odds_today(**args, session_left_frac=1.0) is None


def test_zero_delta_returns_none():
    # Schwab's -999 sentinel is filtered upstream; a genuine 0 delta has no translation.
    assert fill_odds_today(**{**CLSK, "delta": 0.0}, session_left_frac=1.0) is None


def test_closed_session_is_zero_not_none():
    # Distinct from "unknown": we know the answer, and it is no.
    assert fill_odds_today(**CLSK, session_left_frac=0.0) == 0.0


def test_sign_of_delta_does_not_matter():
    assert (fill_odds_today(**{**CLSK, "delta": -0.10}, session_left_frac=1.0)
            == fill_odds_today(**{**CLSK, "delta": 0.10}, session_left_frac=1.0))
