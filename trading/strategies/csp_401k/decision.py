"""Pure management decision core — the canonical tastytrade triad, no I/O.

monitor.py (live) and backtest/engine.py both call this so the rule is tested and
replayed, never reimplemented. Thresholds come from rules.py; reasoning + citations
live in RULES.md §3-§5. P&L is marked at the MID (broker convention) so pnl and
pct_of_max agree in sign — see RULES.md. Every price QUOTED in an action string is the
ask instead, because those strings become Schwab tickets and the mid is not payable.

Verdict priority (RULES.md §3): 2x stop (confirmed, high-VIX-entry) -> strike proximity
-> 2x stop pending/advisory -> 50% target -> 21-DTE manage (CLOSE only if up at the ask
too; HOLD a far-OTM loser, do NOT cut on the clock alone) -> HOLD.
"""
from __future__ import annotations

import math
import sys
from datetime import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rules

_OPEN_ET, _CLOSE_ET = time(9, 30), time(16, 0)
_SESSION_MINUTES = 390.0    # 9:30-16:00 ET


def session_fraction_left(now_et=None):
    """Fraction of a regular session still ahead, in [0, 1]. Pure.

    Before the open (or after the close) returns 1.0 — a resting limit gets a WHOLE
    session, it just isn't today's. The morning cron runs 09:35 ET, so in practice this
    is ~0.99 and a limit posted then has all day to be hit; the same order posted at
    15:50 has ~10 minutes. That difference is the whole reason this exists.
    """
    if now_et is None:
        return 1.0
    t = now_et.time() if hasattr(now_et, "time") else now_et
    if t < _OPEN_ET or t >= _CLOSE_ET:
        return 1.0
    elapsed = (t.hour * 60 + t.minute + t.second / 60.0) - (9 * 60 + 30)
    return max(0.0, min(1.0, 1.0 - elapsed / _SESSION_MINUTES))


def fill_odds_today(*, current_ask, limit_price, price, delta, rv_annual, session_left_frac=1.0):
    """P(the put's offer trades down to `limit_price` before the session ends), or None.

    Returns None when any input is missing — the caller must then say "unknown", never
    silently assume the order won't fill. That silence is the bug this function exists
    to fix: a resting limit two cents inside the spread gets a whole session of chances,
    and reporting only the current ask treats one instantaneous quote as the day's verdict.

    Mechanism, deliberately the cheapest defensible one — no new data, all from the
    chain we already pull:
      1. The offer has to fall by  d = current_ask - limit_price.
      2. A put's price moves with the underlying through delta, so that is an underlying
         RISE of  dS = d / |delta|.
      3. The underlying's own daily sigma is  price * rv_annual/100 / sqrt(252)  (the
         same RV and the same sqrt(252) the no-chase guard uses, RULES.md §1), scaled by
         sqrt(session_left_frac) for the part of the day still ahead.
      4. P(the maximum of a driftless walk touches +dS at any point) = 2*Phi(-dS/sigma)
         by the reflection principle. The factor of 2 IS the "many chances during the
         day" effect — the price only has to trade there once, not close there.

    Honest limits, because this number will be quoted to the account owner:
      - It is P(the price TRADES there), which overstates P(our order is FILLED) —
        someone still has to cross to us, and at a touch we may be behind others in queue.
      - It ignores IV drift and spread narrowing. Both channels usually HELP a resting
        buy limit (a spread that tightens brings the offer down without the stock moving
        at all), so the estimate errs low, which is the safe direction for a "should I
        bother placing it" call.
      - Driftless is the right null: we have no view on the underlying's direction
        intraday, and assuming one would be the no-chase mistake in a new place.
      - RV is trailing 30d, so it is a poor guide on an event day. See RULES.md §5a.
    """
    if current_ask is None or limit_price is None or price is None:
        return None
    if delta is None or rv_annual is None or not rv_annual or not price:
        return None
    if current_ask <= limit_price:
        return 1.0            # already offered at or below our limit
    d = abs(delta)
    if d < 1e-6:
        return None           # no delta => no defensible translation to an underlying move
    frac = max(0.0, min(1.0, session_left_frac if session_left_frac is not None else 1.0))
    if frac <= 0:
        return 0.0
    sigma = price * (rv_annual / 100.0) / math.sqrt(252) * math.sqrt(frac)
    if sigma <= 0:
        return None
    move_needed = (current_ask - limit_price) / d
    # Phi(-x) via erfc, no scipy in this venv.
    return min(1.0, 2.0 * 0.5 * math.erfc(move_needed / (sigma * math.sqrt(2))))


def _pct(odds):
    """Format a probability without ever printing a bare '~0%' for something possible."""
    p = odds * 100
    if 0 < p < 1:
        return "<1%"
    return f"~{p:.0f}%"


def _odds_sentence(*, current_ask, limit_price, price, delta, rv_annual, session_left_frac):
    """' ~N% chance the offer trades there before the close.' — or '' when we can't say.

    Empty when the offer is already at/below the limit (there is nothing to wait for) or
    when the inputs are missing. Never invents a number.
    """
    if current_ask is None or current_ask <= limit_price:
        return ""
    odds = fill_odds_today(current_ask=current_ask, limit_price=limit_price, price=price,
                           delta=delta, rv_annual=rv_annual, session_left_frac=session_left_frac)
    if odds is None:
        return " Ask is above that limit; odds it trades there today unknown (no delta/RV this run)."
    return f" Ask is above that limit — {_pct(odds)} chance it trades there before the close."


def management_verdict(*, credit, current_mid, price, sell_strike, dte,
                       days_in_trade, contracts, rs=rules,
                       entry_vix=None, stop_streak=0, current_ask=None,
                       delta=None, rv_annual=None, session_left_frac=None):
    """Decide CLOSE / CUT / HOLD for one open short put. Pure.

    Args are per-share credit, current put mid, underlying price, short strike, days
    to expiry, days in trade, contract count. Returns the verdict plus the P&L scalars
    every renderer needs, so the formula lives in exactly one place.

    current_ask is the price a buy-to-close actually pays. None keeps the pre-2026-07-31
    mid-only behavior, which is what the backtest wants (Black-Scholes marks have no spread).

    delta / rv_annual / session_left_frac feed fill_odds_today (added 2026-08-03). A close
    is a LIMIT ORDER worked over a session, not a market order at the instantaneous ask,
    so when the ask sits a few cents the wrong side of a target the verdict must state the
    limit to place and the odds it trades there today — never go quiet. All three None
    just drops the odds sentence; the verdict itself is unchanged.

    rs is the threshold source — defaults to the canonical rules module so live
    monitor behavior is unchanged. The backtest sweep (Phase 4) passes a RuleSet
    with the same attribute names to vary thresholds WITHOUT editing rules.py.

    entry_vix / stop_streak condition the mark-based 2x stop (RULES.md §4, 2026-07-07):
    stop_streak is how many CONSECUTIVE prior runs already saw the 2x mark (the caller
    persists it; monitor.py keeps state/stop_streak.json). The returned "stop_streak"
    is the updated count to store. A RuleSet without the new knobs keeps the old
    unconditional stop via the getattr defaults — deliberate for the backtest, whose
    Black-Scholes marks carry no quote artifacts (rules.py STOP_CONFIRM_RUNS note).
    """
    pnl = (credit - current_mid) * 100 * contracts
    pct_of_max = (credit - current_mid) / credit * 100

    capital_at_risk = sell_strike * 100 * contracts
    annualized_return = None
    if pnl > 0 and days_in_trade > 0:
        annualized_return = (pnl / capital_at_risk) / days_in_trade * 365 * 100
    ann_str = f" Annualized: {annualized_return:.0f}%." if annualized_return else ""

    do, alert, actions = "HOLD", False, []

    # Mark-based 2x stop, conditioned two ways (RULES.md §4, 2026-07-07): the mark must
    # PERSIST across STOP_CONFIRM_RUNS consecutive runs (deep-OTM mids can be quote
    # artifacts — BIS Bulletin 95), and the stop auto-CUTs only for high-VIX entries
    # (Project Finance: stops only helped there; passive won in calm regimes). The
    # proximity exit below reads the underlying, not the quote, so it is never deferred.
    stop_hit = rs.STOP_MULTIPLE is not None and current_mid >= credit * rs.STOP_MULTIPLE
    stop_streak_out = stop_streak + 1 if stop_hit else 0
    confirm_runs = getattr(rs, "STOP_CONFIRM_RUNS", 1)
    high_vix_line = getattr(rs, "STOP_HIGH_VIX_ENTRY", None)
    stop_active = high_vix_line is None or entry_vix is None or entry_vix >= high_vix_line

    if stop_hit and stop_active and stop_streak_out >= confirm_runs:
        do, alert = "CUT", True
        actions.append(
            f"CUT — put at ${current_mid:.2f} is {rs.STOP_MULTIPLE:g}x your ${credit:.2f} credit "
            f"(P&L ~${pnl:+,.0f}), confirmed on {stop_streak_out} consecutive runs. "
            f"Stop rule hit (RULES.md §4): buy to close or roll."
        )
    elif price <= sell_strike * (1 + rs.STRIKE_PROXIMITY_PCT / 100):
        do, alert = "CUT", True
        actions.append(
            f"CUT (strike proximity) — at ${price:.2f} is within "
            f"{rs.STRIKE_PROXIMITY_PCT:.0f}% of the ${sell_strike} strike. Risk exit (RULES.md §4)."
        )
    elif stop_hit and stop_active:
        # First sighting of the 2x mark: alert, don't cut yet. One inflated mid on a
        # deep-OTM put is exactly what the Aug-2024 spread blowout produced (spreads
        # >80% of mid) — if the loss is real, the mark will still be there next run.
        do, alert = "HOLD", True
        actions.append(
            f"STOP PENDING — put at ${current_mid:.2f} is {rs.STOP_MULTIPLE:g}x your "
            f"${credit:.2f} credit (P&L ~${pnl:+,.0f}), run {stop_streak_out} of "
            f"{confirm_runs} needed. Deep-OTM mids can be quote artifacts (RULES.md §4); "
            f"CUT fires if it persists next run. Proximity/bad-news exits still immediate."
        )
    elif stop_hit:
        # Low-VIX entry: the mark-based stop is advisory, not automatic — in calm
        # regimes fixed stops cut trades that mean-revert (Project Finance). The
        # close stays a logged judgment call; proximity/bad-news exits stand above.
        do, alert = "HOLD", True
        actions.append(
            f"STOP ADVISORY — put at ${current_mid:.2f} is {rs.STOP_MULTIPLE:g}x your "
            f"${credit:.2f} credit (P&L ~${pnl:+,.0f}), but this was a low-VIX entry "
            f"(VIX {entry_vix:.1f} at open < {high_vix_line:g}): passive management had "
            f"the edge in calm regimes (RULES.md §4). Cutting here is a judgment call — "
            f"log it. Proximity/bad-news exits still fire on their own."
        )
    elif pct_of_max >= rs.PROFIT_TARGET_PCT:
        do, alert = "CLOSE", True
        # A close is a LIMIT worked over a session, not a market order at the instantaneous
        # ask. Quote the 50% mark — the canonical target and the price the account owner actually rests
        # (RULES.md §3) — and, when the ask is above it, the odds it trades there today
        # rather than pretending one quote settled it.
        target = round(credit * rs.PROFIT_TARGET_PCT / 100, 2)
        # If the offer is already through the target, quote the OFFER, not the target: a
        # buy limit at the higher target fills at the lower offer anyway, so naming the
        # target would just be a worse-looking ticket for the same fill.
        if current_ask is not None and current_ask < target:
            target = round(current_ask, 2)
        odds_s = _odds_sentence(current_ask=current_ask, limit_price=target, price=price,
                                delta=delta, rv_annual=rv_annual,
                                session_left_frac=session_left_frac)
        actions.append(
            f"CLOSE — {pct_of_max:.0f}% of max profit (>= {rs.PROFIT_TARGET_PCT:.0f}% target) "
            f"in {days_in_trade} days. Buy to close, limit ${target:.2f} (the {rs.PROFIT_TARGET_PCT:.0f}% mark; "
            f"ask ${current_ask:.2f}, mid ${current_mid:.2f}, P&L ~${pnl:+,.0f} at the mid).{odds_s}{ann_str} "
            f"Take the win (RULES.md §3) — do NOT gate on cushion or redeployment."
            if current_ask is not None else
            f"CLOSE — {pct_of_max:.0f}% of max profit (>= {rs.PROFIT_TARGET_PCT:.0f}% target) "
            f"in {days_in_trade} days. Buy to close, limit ${target:.2f} (P&L ~${pnl:+,.0f} at the mid).{ann_str} "
            f"Take the win (RULES.md §3) — do NOT gate on cushion or redeployment."
        )
    elif dte is not None and rs.MANAGE_DTE is not None and dte <= rs.MANAGE_DTE:
        alert = True
        # "Up at the timer" must mean up at the price a close actually PAYS — the ask,
        # not the mid (CLSK 2026-07-31: mid 0.295 on a 0.25/0.34 quote read +$3 and
        # fired CLOSE, but buying at 0.34 was -$24; the same run 25 min earlier had
        # mid 0.455 and said HOLD). On a deep-OTM put the spread routinely exceeds the
        # whole remaining win, so a mid-only test flips sign on quote noise and books a
        # real loss to "take a win." Same quote-artifact reasoning as STOP_CONFIRM_RUNS
        # above. The exit price is the ask when we have it; the mid is the fallback.
        exit_price = current_ask if current_ask is not None else current_mid
        pnl_at_exit = (credit - exit_price) * 100 * contracts
        if pnl > 0 and pnl_at_exit > 0:
            do = "CLOSE"
            actions.append(
                f"CLOSE (21-DTE manage) — {dte} days left (<= {rs.MANAGE_DTE} DTE), "
                f"{pct_of_max:.0f}% of max. Gamma rising; take the win — buy to close at the "
                f"${exit_price:.2f} ask (P&L ~${pnl_at_exit:+,.0f}). "
                f"Exception: a deep-cushion put may be held through imminent earnings for the IV crush (RULES.md §5)."
            )
        elif pnl > 0:
            # Up at the mid, under water at the ask. Do NOT go quiet here (the 2026-08-03
            # correction): a close is a limit worked over a session, so "the ask is a few
            # cents too high right now" is not the day's answer. State the limit that makes
            # it a real win — breakeven is the credit, so anything below it — and the odds
            # the offer trades there before the close. the account owner places the order and sees if
            # it hits; that decision is his, and it needs the number, not silence.
            # Still never CUT: a position whose entire loss is the spread has cleared no
            # risk gate, so if the limit doesn't fill it simply rides (RULES.md §3/§4).
            do, alert = "WORK", True
            workable = min(round(current_mid, 2), round(credit - 0.01, 2))
            odds = fill_odds_today(current_ask=current_ask, limit_price=workable, price=price,
                                   delta=delta, rv_annual=rv_annual,
                                   session_left_frac=session_left_frac)
            pnl_at_limit = (credit - workable) * 100 * contracts
            if odds is None:
                odds_s = " Odds it trades there today: unknown (no delta/RV this run)."
            elif odds * 100 >= getattr(rs, "FILL_ODDS_WORKABLE_PCT", 25):
                odds_s = f" ~{odds * 100:.0f}% chance the offer trades there before the close — worth resting."
            else:
                odds_s = (f" Only {_pct(odds)} chance it trades there before today's close; "
                          f"rest it GTC anyway if you want the fill — an unfilled limit costs nothing "
                          f"and today is not its only session.")
            actions.append(
                f"WORK THE LIMIT (21-DTE timer, win is inside the spread) — up ${pnl:+,.0f} at the "
                f"${current_mid:.2f} mid but ${pnl_at_exit:+,.0f} at the ${exit_price:.2f} ask, so paying "
                f"the ask books a loss. Place a buy-to-close limit at ${workable:.2f} "
                f"(P&L ~${pnl_at_limit:+,.0f} if it fills).{odds_s} "
                f"${price:.2f} is well above the ${sell_strike:g} strike, so if it doesn't fill it just "
                f"rides — the 2x-stop and strike-proximity exits still stand (RULES.md §3/§4)."
            )
        elif getattr(rs, "MANAGE_DTE_CUTS_LOSERS", True):
            do = "CUT"
            actions.append(
                f"CUT (21-DTE manage) — {dte} days left (<= {rs.MANAGE_DTE} DTE), still underwater "
                f"(P&L ~${pnl:+,.0f}). Gamma risk isn't worth the remaining theta; close or roll."
            )
        else:
            # Far-OTM loser past the timer: it has already cleared the 2x-stop and the
            # strike-proximity gate above, so it is NOT catastrophic and NOT near
            # assignment — it is "down" only on IV markup. Time alone is not a reason to
            # realize a loss on a bet whose strike isn't threatened; hold to expiry. The
            # real risk exits (stop, proximity, bad news) still fire above this branch.
            # RULES.md §3/§4. alert=False so a HOLD never pings; it just shows its reason.
            do, alert = "HOLD", False
            actions.append(
                f"HOLD (21-DTE timer, far OTM) — {dte} days left, but ${price:.2f} is well above "
                f"the ${sell_strike:g} strike; the ${pnl:+,.0f} mark is IV markup, not assignment risk. "
                f"Time alone isn't a cut — let it ride. The 2x-stop and strike-proximity exits still stand (RULES.md §4)."
            )

    return {
        "pnl": pnl, "pct_of_max": pct_of_max, "annualized_return": annualized_return,
        "do": do, "alert": alert, "actions": actions,
        "stop_hit": stop_hit, "stop_streak": stop_streak_out,
    }
