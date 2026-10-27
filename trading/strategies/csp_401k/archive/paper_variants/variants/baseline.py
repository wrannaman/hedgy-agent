"""
Baseline variant — mirrors the current live rules as the reference for all
experiments.

The live account still runs off the root scripts (daily_scan.py, recommend.py,
monitor.py). This module duplicates the rules in a declarative form so the
variant engine (experiments/paper_runner.py, experiments/replay.py) has a
fair comparison point for experimental variants.

When/if an experimental variant earns promotion, it replaces this file and the
old baseline is archived.

Rules (copy of current live):
- Entry: watchlist name down >=3% OR market fear (SPY/QQQ <=-1.5%) OR VIX >=25
- No earnings within 45 days
- Strike: 7-10% OTM, highest bid
- DTE: 28-45
- Manage: 2x credit -> stop; 75% profit -> close; DTE<=7 -> close any;
          stock within 5% of strike -> alert
"""
from datetime import datetime, timedelta, date
from variants._base import EntrySignal, Order, ManagementAction

name = "baseline"
description = (
    "Current live rules: red-day entry, 7-10% OTM, 28-45 DTE, "
    "75% profit / 2x stop / DTE<=7 close"
)

DCA_THRESHOLD = -3.0
MARKET_FEAR = -1.5
VIX_ELEVATED = 25.0


def entry_signals(market_state):
    """Scan today's market state and return any entry signals.

    market_state shape (from experiments/snapshot.py):
        {
          "date": "YYYY-MM-DD",
          "spy_change": float, "qqq_change": float, "vix": float|None,
          "names": {
              "NVDA": {"price": 170.0, "change_pct": -3.5, "earnings": "...", ...},
              ...
          }
        }
    """
    signals = []
    spy_change = market_state.get("spy_change") or 0
    qqq_change = market_state.get("qqq_change") or 0
    vix = market_state.get("vix") or 0
    market_fear = spy_change <= MARKET_FEAR or qqq_change <= MARKET_FEAR
    vix_high = vix >= VIX_ELEVATED
    today = datetime.strptime(market_state["date"], "%Y-%m-%d").date()

    for symbol, info in market_state.get("names", {}).items():
        change = info.get("change_pct") or 0
        name_dip = change <= DCA_THRESHOLD
        if not (name_dip or market_fear or vix_high):
            continue

        earnings_str = info.get("earnings")
        if earnings_str:
            earnings = datetime.strptime(earnings_str, "%Y-%m-%d").date()
            if today <= earnings <= today + timedelta(days=45):
                continue

        reasons = []
        if name_dip:
            reasons.append(f"{symbol} {change:+.1f}%")
        if market_fear:
            reasons.append(f"SPY {spy_change:+.1f}%")
        if vix_high:
            reasons.append(f"VIX {vix:.0f}")

        signals.append(EntrySignal(
            symbol=symbol,
            reason=" + ".join(reasons),
            target_dte=(28, 45),
            target_otm_pct=(7.0, 10.0),
            instrument="cash_secured_put",
            priority=int(-change),
            meta={"change_pct": change, "price": info.get("price")},
        ))

    return sorted(signals, key=lambda s: -s.priority)


def compose_order(signal, market_state, client):
    """Fetch the live chain and pick the specific contract."""
    today = date.today()
    min_dte, max_dte = signal.target_dte
    min_otm, max_otm = signal.target_otm_pct

    resp = client.get_option_chain(
        symbol=signal.symbol,
        contract_type=client.Options.ContractType.PUT,
        strike_count=30,  # 10 was too tight — Schwab pads oddly, missed 7-10% OTM strikes on TSM
        from_date=today + timedelta(days=min_dte),
        to_date=today + timedelta(days=max_dte),
    )
    resp.raise_for_status()
    chain = resp.json()
    price = chain.get("underlyingPrice", 0)
    if not price:
        return None

    candidates = []
    for exp, strikes in chain.get("putExpDateMap", {}).items():
        for _, contract_list in strikes.items():
            for c in contract_list:
                strike = c["strikePrice"]
                bid = c["bid"]
                if bid <= 0 or strike >= price:
                    continue
                otm_pct = (price - strike) / price * 100
                if not (5 <= otm_pct <= 12):
                    continue
                candidates.append({
                    "strike": strike, "bid": bid, "ask": c["ask"],
                    "dte": c["daysToExpiration"],
                    "delta": c.get("delta", 0), "otm_pct": otm_pct,
                    "expiration": c.get("expirationDate", "")[:10],
                })

    sweet = [c for c in candidates if min_otm <= c["otm_pct"] <= max_otm]
    pool = sweet if sweet else candidates
    if not pool:
        return None
    pool.sort(key=lambda c: c["bid"], reverse=True)
    pick = pool[0]
    limit = round(pick["bid"] + 0.05, 2)

    return Order(
        action="SELL_TO_OPEN",
        instrument="cash_secured_put",
        symbol=signal.symbol,
        sell_strike=pick["strike"],
        buy_strike=None,
        expiration=pick["expiration"],
        contracts=1,
        limit_price=limit,
        current_price=price,
        otm_pct=pick["otm_pct"],
        delta=pick["delta"],
        dte=pick["dte"],
    )


def manage_position(position, market_state):
    """Decide action for an open position.

    position must carry: sell_strike, limit_price (credit/share), contracts,
    current_mid, current_ask, current_stock, current_dte.
    The caller is responsible for fetching and attaching those.
    """
    current_mid = position.get("current_mid")
    credit_per_share = position["limit_price"]
    dte = position.get("current_dte")
    stock_price = position.get("current_stock")

    if current_mid is None:
        return ManagementAction("hold", "no current quote", "info")

    if current_mid >= credit_per_share * 2.0:
        return ManagementAction(
            "close",
            f"STOP LOSS: put ${current_mid:.2f} >= 2x credit ${credit_per_share:.2f}",
            "immediate",
        )

    pct_of_max = (credit_per_share - current_mid) / credit_per_share * 100
    if pct_of_max >= 75:
        return ManagementAction(
            "close", f"75% profit target ({pct_of_max:.0f}% of max)", "normal"
        )

    if dte is not None and dte <= 7:
        kind = "profit" if pct_of_max > 0 else "loss"
        return ManagementAction(
            "close", f"DTE {dte}, close any {kind}", "normal"
        )

    if stock_price is not None and stock_price <= position["sell_strike"] * 1.05:
        return ManagementAction(
            "alert",
            f"Stock ${stock_price:.2f} within 5% of strike ${position['sell_strike']}",
            "normal",
        )

    if pct_of_max >= 50:
        return ManagementAction(
            "hold",
            f"{pct_of_max:.0f}% of max — check for VIX/catalyst overrides",
            "info",
        )

    return ManagementAction("hold", "within trade rules", "info")
