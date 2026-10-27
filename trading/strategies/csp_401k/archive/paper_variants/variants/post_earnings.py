"""
Post-earnings-crush variant — T+1 to T+3 after earnings, IV still elevated.

Thesis (per Sinclair, TastyLive systematic studies): right after earnings, the
binary event risk is gone but implied volatility stays elevated for a few days
while the market digests. Selling premium into that decaying IV is a classic
variance-risk-premium play. Unlike baseline — which BLOCKS earnings windows —
this variant SEEKS the T+1..T+3 window specifically.

Rules:
- Entry: days_from_earnings in {1, 2, 3} (earnings just happened)
           AND atm_iv_30d >= 35% (proxy for IV still elevated — swap to IVR>=50
           once we have ~250 days of snapshot history).
- Strike: 7-10% OTM, highest bid (same as baseline for fair comparison)
- DTE: 14-28 (shorter cycle than baseline's 28-45)
- Manage: reuses baseline (75% profit / 2x stop / DTE<=7 close)

Why the IV floor at 35%: today's watchlist ranges from ~28% (NFLX, AAPL) to
~90% (HUBS). 35% excludes the calmest names that wouldn't pay enough to justify
the gamma. It's a first-pass threshold — revisit after 20 trades.
"""
from variants._base import EntrySignal
# Reuse baseline's strike picker and management rules so only entry logic differs
from variants.baseline import compose_order, manage_position  # noqa: F401

name = "post_earnings"
description = (
    "T+1..T+3 post-earnings + IV>=35%, 7-10% OTM, 14-28 DTE, "
    "baseline management (75%/2x/DTE7)"
)

POST_EARNINGS_WINDOW = (1, 3)  # days_from_earnings inclusive range
IV_FLOOR = 35.0                # atm_iv_30d percent, proxy for IVR until we have history


def entry_signals(market_state):
    """Fire on names that just reported AND still carry elevated IV."""
    signals = []
    min_t, max_t = POST_EARNINGS_WINDOW

    for symbol, info in market_state.get("names", {}).items():
        dfe = info.get("days_from_earnings")
        iv = info.get("atm_iv_30d")
        if dfe is None or iv is None:
            continue
        if not (min_t <= dfe <= max_t):
            continue
        if iv < IV_FLOOR:
            continue

        change = info.get("change_pct") or 0
        signals.append(EntrySignal(
            symbol=symbol,
            reason=f"{symbol} T+{dfe} post-earnings, IV {iv:.1f}%",
            target_dte=(14, 28),
            target_otm_pct=(7.0, 10.0),
            instrument="cash_secured_put",
            priority=int(iv),  # higher IV = higher priority
            meta={
                "days_from_earnings": dfe,
                "atm_iv_30d": iv,
                "change_pct": change,
                "price": info.get("price"),
            },
        ))

    return sorted(signals, key=lambda s: -s.priority)
