"""
Trade recommendation engine. Given an actionable signal, compose the EXACT order.
This is what turns "NVDA is down 3%" into "Sell 1 NVDA Apr 24 $160 put, limit $3.80, day order."

Called by the cron system when daily_scan or monitor detects an opportunity.
"""
import os
import sys
import requests
from datetime import datetime, timedelta
from pathlib import Path
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
from shared.auth import get_client
from shared.accounts import account_by_suffix, configured_account_suffix
from trade_log import load_log
from scan_log import log_alert
import rules  # canonical thresholds — single source of truth (see RULES.md)

from shared.notifications import post_message


def get_account_cash(client):
    """Get actual available cash from Schwab."""
    acct = account_by_suffix(client, configured_account_suffix())

    from schwab import client as sc
    resp = client.get_account(acct["hashValue"], fields=[sc.Client.Account.Fields.POSITIONS])
    resp.raise_for_status()
    sa = resp.json().get("securitiesAccount", {})
    bal = sa.get("currentBalances", {})

    cash = bal.get("cashBalance", 0)

    # Subtract locked collateral, but only for positions the account actually holds.
    # A logged-open trade that never filled must not lock cash (see reconcile.py).
    from reconcile import reconcile, warn_phantoms
    open_trades = [t for t in load_log().get("trades", []) if t["status"] == "open"]
    confirmed, phantom = reconcile(open_trades, sa.get("positions", []))
    warn_phantoms(phantom)
    locked = sum(t["sell_strike"] * 100 * t["contracts"]
                 for t in confirmed if t["strategy"] == "cash_secured_put")

    return cash, locked, max(cash - locked, 0)


def recommend_put(client, symbol, current_price, book_cash=None):
    """
    Compose a specific cash-secured put recommendation.
    Picks a strike ~8-10% OTM, 30-45 DTE, and returns the exact order.

    book_cash sizes the position (rules.position_contracts: POSITION_TARGET_PCT of the
    book on assignment exposure, floor 1 — RULES.md §7). None = 1 contract, legacy.
    """
    today = datetime.now().date()

    resp = client.get_option_chain(
        symbol=symbol,
        contract_type=client.Options.ContractType.PUT,
        strike_count=10,
        from_date=today + timedelta(days=rules.DTE_MIN),
        to_date=today + timedelta(days=rules.DTE_MAX),
    )
    resp.raise_for_status()
    chain = resp.json()
    price = chain.get("underlyingPrice", 0)

    # Find best put: 5-10% OTM, best premium
    candidates = []
    put_map = chain.get("putExpDateMap", {})
    for exp, strikes_data in put_map.items():
        for strike_str, contract_list in strikes_data.items():
            for c in contract_list:
                strike = c["strikePrice"]
                bid = c["bid"]
                dte = c["daysToExpiration"]
                if bid <= 0 or strike >= price:
                    continue
                otm_pct = (price - strike) / price * 100
                if 5 <= otm_pct <= 12:
                    candidates.append({
                        "strike": strike,
                        "bid": bid,
                        "ask": c["ask"],
                        "mid": (bid + c["ask"]) / 2,
                        "dte": dte,
                        "delta": c.get("delta", 0),
                        "otm_pct": otm_pct,
                        "expiration": c.get("expirationDate", "")[:10],
                        "symbol": c.get("symbol", ""),
                    })

    if not candidates:
        return None

    # Pick the one with best premium in the 7-10% OTM sweet spot
    sweet = [c for c in candidates if 7 <= c["otm_pct"] <= 10]
    if not sweet:
        sweet = candidates
    sweet.sort(key=lambda x: x["bid"], reverse=True)
    pick = sweet[0]

    # Limit price: bid + a little greed
    limit = round(pick["bid"] + 0.05, 2)

    # Position size on assignment exposure (RULES.md §7): POSITION_TARGET_PCT of the
    # book, floor 1 contract. The fits-cash check below still gates the total.
    quantity = rules.position_contracts(pick["strike"], book_cash) if book_cash else 1

    cash_required = pick["strike"] * 100 * quantity
    premium = limit * 100 * quantity
    breakeven = pick["strike"] - limit

    # The standing-order pair (RULES.md §3): the GTC buy-to-close to set the moment
    # this fills (50% mark), and the date to cancel it and manage by hand (21 DTE).
    gtc_on_fill = round(limit * rules.PROFIT_TARGET_PCT / 100, 2)
    manage_by = None
    if pick["expiration"]:
        try:
            manage_by = (datetime.strptime(pick["expiration"], "%Y-%m-%d").date()
                         - timedelta(days=rules.MANAGE_DTE)).isoformat()
        except ValueError:
            pass

    return {
        "action": "SELL TO OPEN",
        "symbol": symbol,
        "type": "PUT",
        "strike": pick["strike"],
        "expiration": pick["expiration"],
        "dte": pick["dte"],
        "quantity": quantity,
        "limit_price": limit,
        "order_type": "LIMIT",
        "duration": "DAY",
        "premium_collected": premium,
        "cash_required": cash_required,
        "breakeven": breakeven,
        "otm_pct": pick["otm_pct"],
        "delta": pick["delta"],
        "current_price": price,
        "gtc_on_fill": gtc_on_fill,
        "manage_by": manage_by,
    }


def recommend_close(trade, current_mid, current_ask):
    """Compose a specific close order for an open position."""
    # Buy to close at the ask (or slightly below)
    limit = round(current_ask, 2)
    # credit is TOTAL dollars across contracts; per-share = credit / (100 * contracts)
    pnl = (trade["credit"] / (100 * trade["contracts"]) - limit) * 100 * trade["contracts"]

    return {
        "action": "BUY TO CLOSE",
        "symbol": trade["symbol"],
        "type": "PUT",
        "strike": trade["sell_strike"],
        "expiration": trade["expiration"],
        "quantity": trade["contracts"],
        "limit_price": limit,
        "order_type": "LIMIT",
        "duration": "DAY",
        "estimated_pnl": pnl,
        "reason": "50% profit target reached",
    }


def format_order_for_slack(rec, cash_available=None):
    """Format a recommendation as a Slack message the account owner can execute in 30 seconds."""
    lines = []

    if rec["action"] == "SELL TO OPEN":
        lines.append(f"*TRADE ALERT: {rec['symbol']} PUT*")
        lines.append("")
        lines.append(f"Action: {rec['action']}")
        lines.append(f"Symbol: {rec['symbol']}")
        lines.append(f"Type: Put")
        lines.append(f"Strike: ${rec['strike']:.0f}")
        lines.append(f"Expiration: {rec['expiration']}")
        lines.append(f"Quantity: {rec['quantity']}")
        lines.append(f"Limit Price: ${rec['limit_price']:.2f}")
        lines.append(f"Duration: Day")
        lines.append("")
        lines.append(f"You collect: ${rec['premium_collected']:.0f}")
        lines.append(f"Cash locked: ${rec['cash_required']:,.0f}")
        if cash_available is not None:
            lines.append(f"Cash available: ${cash_available:,.0f}")
            lines.append(f"Cash after: ${cash_available - rec['cash_required']:,.0f}")
        lines.append(f"Break-even: ${rec['breakeven']:.2f} ({rec['otm_pct']:.0f}% below current ${rec['current_price']:.2f})")

    elif rec["action"] == "BUY TO CLOSE":
        lines.append(f"*CLOSE TRADE: {rec['symbol']} ${rec['strike']:.0f} PUT*")
        lines.append("")
        lines.append(f"Action: {rec['action']}")
        lines.append(f"Symbol: {rec['symbol']}")
        lines.append(f"Strike: ${rec['strike']:.0f}")
        lines.append(f"Expiration: {rec['expiration']}")
        lines.append(f"Quantity: {rec['quantity']}")
        lines.append(f"Limit Price: ${rec['limit_price']:.2f}")
        lines.append(f"Duration: Day")
        lines.append("")
        lines.append(f"Estimated P&L: ${rec['estimated_pnl']:+,.0f}")
        lines.append(f"Reason: {rec['reason']}")

    return "\n".join(lines)


def send_slack(message):
    """Explicit notification helper; safe errors never include a webhook URL."""
    return post_message(message)


def run_recommendation(signal_type, **kwargs):
    """
    Generate and send a specific trade recommendation.

    signal_type: "new_put", "close_position"
    """
    client = get_client()
    cash, locked, available = get_account_cash(client)

    if signal_type == "new_put":
        symbol = kwargs["symbol"]
        price = kwargs["price"]
        rec = recommend_put(client, symbol, price, book_cash=cash)
        if rec and rec["cash_required"] <= available:
            msg = format_order_for_slack(rec, cash_available=available)
            print(msg)
            sent = send_slack(msg)
            log_alert(msg, sent_slack=sent)
            return rec
        elif rec:
            print(f"Can't afford: {symbol} put needs ${rec['cash_required']:,.0f}, only ${available:,.0f} available")
            return None

    elif signal_type == "close_position":
        trade = kwargs["trade"]
        current_mid = kwargs["current_mid"]
        current_ask = kwargs["current_ask"]
        rec = recommend_close(trade, current_mid, current_ask)
        msg = format_order_for_slack(rec)
        print(msg)
        sent = send_slack(msg)
        log_alert(msg, sent_slack=sent)
        return rec

    # REMOVED 2026-07-07: the "dca_buy" share-purchase alert. This desk is options-only
    # (CRON_PROMPT) — long-term-hold share advice never comes from the options scanner.

    return None


if __name__ == "__main__":
    # Test: what would we recommend for NVDA right now?
    client = get_client()
    resp = client.get_quotes(["NVDA"])
    resp.raise_for_status()
    price = resp.json()["NVDA"]["quote"]["lastPrice"]

    print(f"NVDA at ${price:.2f}\n")
    rec = recommend_put(client, "NVDA", price)
    if rec:
        cash, locked, available = get_account_cash(client)
        print(format_order_for_slack(rec, cash_available=available))
    else:
        print("No suitable put found.")
