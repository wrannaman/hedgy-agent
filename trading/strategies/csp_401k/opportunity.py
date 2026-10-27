"""Opportunity-cost surfacing for held positions — the "is there a better home for
this collateral?" comparison for the judgment layer.

This is a SURFACING tool, not a verdict. It never emits CLOSE/CUT and never auto-trades.
For a position the management core (decision.py) already decided to HOLD, it answers one
question: does the day's screener have a materially better, positive-edge trade that
would fit the cash this position frees if closed? If so, monitor.py attaches an
informational note for the judgment layer to weigh and log. The close decision stays
human; opportunity cost is context rather than a calendar-driven exit (RULES.md §3).

Why surfacing, not a gate: the strategy once had an invented OPPORTUNITY_EXIT_BEAT_RATIO
that auto-decided CLOSE/HOLD in code and tangled into a wrong verdict; it was removed
2026-06-18 (RULES.md §3). The lesson kept: opportunity cost INFORMS judgment, it does not
mechanically pull the trigger. The beat ratio here is an explicit, tunable appetite knob
(rules.py), labeled heuristic — not a backtested threshold.

The yardstick is the same for both sides so they compare apples-to-apples: annualized
premium yield on the collateral committed. For the held position the "premium still at
stake" is current_mid (what holding to a clean OTM expiry recovers vs closing now); for a
candidate it is its own mid. Contract count cancels (one contract per underlying).
"""
from __future__ import annotations


def annualized_yield_pct(mid, strike, dte):
    """Premium as an annualized % of the collateral it ties up. 0.0 if undefined."""
    if not mid or not strike or not dte or dte <= 0:
        return 0.0
    return (mid / strike) * (365.0 / dte) * 100.0


def best_redeploy(*, held, candidates, free_cash, beat_ratio):
    """The best positive-edge candidate that materially beats holding `held` AND fits the
    cash freed by closing it, or None. Pure — monitor.py does the I/O (reads last_screen).

    held: {symbol, current_mid, strike, dte, contracts}
    candidates: list of screener dicts (last_screen.json 'candidates')
    free_cash: cash available BEFORE closing held; closing frees held's collateral.
    beat_ratio: a candidate must earn >= this multiple of the hold's annualized yield.
    """
    hold_yield = annualized_yield_pct(held["current_mid"], held["strike"], held["dte"])
    if hold_yield <= 0:
        return None
    contracts = held.get("contracts", 1)
    freed = held["strike"] * 100 * contracts
    budget = (free_cash or 0.0) + freed

    best = None
    for c in candidates:
        if c.get("symbol") == held.get("symbol"):
            continue                                   # one position per underlying
        if (c.get("ev_dollars") or 0) <= 0:
            continue                                   # no real edge -> not a better home
        if not c.get("actionable"):
            continue                                   # thin edge -> not worth the churn (RULES.md §1a)
        collateral = c.get("collateral") or 0
        if collateral <= 0 or collateral > budget:
            continue                                   # doesn't fit even after freeing held
        cand_yield = annualized_yield_pct(c.get("mid"), c.get("strike"), c.get("dte"))
        if cand_yield < hold_yield * beat_ratio:
            continue                                   # not materially better
        if best is None or cand_yield > best["cand_yield_pct"]:
            best = {
                "symbol": c["symbol"],
                "strike": c["strike"],
                "dte": c["dte"],
                "mid": c["mid"],
                "premium_dollars": c.get("premium_dollars"),
                "collateral": collateral,
                "ev_dollars": c.get("ev_dollars"),
                "vrp": c.get("vrp"),
                "p_assign_pct": c.get("p_assign_pct"),
                "cand_yield_pct": round(cand_yield, 1),
                "hold_yield_pct": round(hold_yield, 1),
                "beats_by": round(cand_yield / hold_yield, 2),
            }
    return best
