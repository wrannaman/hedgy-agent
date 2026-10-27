"""
Pre-trade checklist. Run this BEFORE any trade to check conditions.
This is the emotional buffer — it says "go" or "wait" based on data, not feelings.
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.auth import get_client
from trade_log import check_loss_streak, check_sizing_consistency, load_log
from event_scanner import scan_events, format_report, EARNINGS_CALENDAR
from daily_scan import get_cash_status

# Correlated groups — don't stack positions in the same group
CORRELATION_GROUPS = {
    "semis": ["NVDA", "AMD", "TSM", "ASML"],
    "mega_tech": ["GOOGL", "META", "AMZN", "AAPL", "MSFT"],
    "high_beta_tech": ["COIN", "SHOP", "NET"],
}


def check_market_conditions(client):
    """Check if today is a good day to sell premium."""
    # Use SPY as market proxy and VIX for fear (Schwab uses $VIX)
    resp = client.get_quotes(["$VIX", "SPY", "QQQ"])
    resp.raise_for_status()
    data = resp.json()

    results = {"pass": True, "signals": [], "warnings": []}

    # VIX check
    vix_data = data.get("$VIX", data.get("$VIX.X", data.get("VIX", {})))
    vix_quote = vix_data.get("quote", {}) if vix_data else {}
    vix = vix_quote.get("lastPrice", 0)

    if vix > 0:
        if vix >= 25:
            results["signals"].append(f"VIX at {vix:.1f} — ELEVATED FEAR. Good day to sell premium.")
        elif vix >= 20:
            results["signals"].append(f"VIX at {vix:.1f} — moderate fear. Decent premiums.")
        elif vix >= 15:
            results["signals"].append(f"VIX at {vix:.1f} — calm market. Premiums are thinner.")
        else:
            results["warnings"].append(f"VIX at {vix:.1f} — very low fear. Premiums are cheap. Consider waiting.")

    # SPY/QQQ direction today
    for sym in ["SPY", "QQQ"]:
        q = data.get(sym, {}).get("quote", {})
        change = q.get("netPercentChange", 0)
        if change < -1.5:
            results["signals"].append(f"{sym} down {change:.1f}% today — FEAR DAY. Good for selling puts.")
        elif change < -0.5:
            results["signals"].append(f"{sym} down {change:.1f}% today — mild red. Acceptable.")
        elif change > 1.0:
            results["warnings"].append(f"{sym} up {change:.1f}% today — green day. Premiums are deflated. Consider waiting.")
        else:
            results["signals"].append(f"{sym} {change:+.1f}% today — neutral.")

    return results, vix


def check_earnings(symbol, expiration_date):
    """Report whether the option expiration spans an earnings date — context only.

    NEVER blocks. Earnings is not a disqualifier (RULES.md §5): the screener already
    forces the strike outside the option-implied earnings move, so a print in the
    window is covered by the cushion, not by fleeing the trade. This stays as an
    informational note for sizing the bimodal tail (RULES.md §7).
    """
    earnings_str = EARNINGS_CALENDAR.get(symbol)
    if not earnings_str:
        return {"pass": True, "message": f"No earnings date on file for {symbol}."}

    earnings = datetime.strptime(earnings_str, "%Y-%m-%d").date()
    today = datetime.now().date()

    if today < earnings < expiration_date:
        days_to_earnings = (earnings - today).days
        return {
            "pass": True,
            "message": f"{symbol} earnings on {earnings_str} ({days_to_earnings} days away) falls before "
                       f"expiration {expiration_date}. Not a blocker — cushion sits outside the implied move "
                       f"(RULES.md §5). Size for the tail (§7).",
        }

    return {"pass": True, "message": f"{symbol} earnings {earnings_str} — outside the trade window."}


def check_correlation(symbol, existing_positions):
    """Check if adding this symbol creates correlated risk."""
    for group_name, members in CORRELATION_GROUPS.items():
        if symbol in members:
            overlap = [s for s in existing_positions if s in members]
            if overlap:
                return {
                    "pass": False,
                    "message": f"WARNING: {symbol} is in the '{group_name}' group with existing position(s): "
                               f"{', '.join(overlap)}. A sector selloff hits both."
                }
    return {"pass": True, "message": f"No correlation conflict for {symbol}."}


def check_liquidity(client, option_symbol):
    """Check bid-ask spread on the specific option."""
    # Parse the underlying from the option symbol
    resp = client.get_quotes([option_symbol])
    resp.raise_for_status()
    data = resp.json()

    for sym, info in data.items():
        q = info.get("quote", {})
        bid = q.get("bidPrice", 0)
        ask = q.get("askPrice", 0)
        if bid > 0 and ask > 0:
            mid = (bid + ask) / 2
            spread_pct = (ask - bid) / mid * 100
            if spread_pct > 5:
                return {"pass": False, "message": f"Wide spread: ${bid:.2f}/${ask:.2f} ({spread_pct:.1f}%). Edge gets eaten by slippage."}
            else:
                return {"pass": True, "message": f"Spread OK: ${bid:.2f}/${ask:.2f} ({spread_pct:.1f}%)"}

    return {"pass": True, "message": "Could not check liquidity."}


def check_position_size(risk_amount, net_available):
    """The only sizing limit: the collateral must fit in free cash. No per-trade
    % cap — one contract per underlying is the unit (see CLAUDE.md)."""
    if risk_amount > net_available:
        return {
            "pass": False,
            "message": f"Collateral ${risk_amount:,.0f} exceeds free cash ${net_available:,.0f} — not enough to cover one contract."
        }
    headroom = net_available - risk_amount
    return {
        "pass": True,
        "message": f"Collateral ${risk_amount:,.0f} fits in free cash ${net_available:,.0f} (${headroom:,.0f} left after)."
    }


def check_upcoming_events(symbol, expiration_date, web_events=None):
    """Check for upcoming catalyst events (FOMC, CPI, court cases, regulatory, etc.)."""
    result = scan_events(symbol, expiration_date, web_events=web_events)

    if result["verdict"] == "RED":
        return {
            "pass": False,
            "message": f"RED — High-impact event(s) before expiration. Review carefully.",
            "details": result["summary"],
            "search_queries": result["search_queries"],
            "web_searched": result["web_searched"],
        }
    elif result["verdict"] == "YELLOW":
        return {
            "pass": True,  # warning but not blocking
            "message": f"YELLOW — Moderate events or web search not yet run.",
            "details": result["summary"],
            "search_queries": result["search_queries"],
            "web_searched": result["web_searched"],
        }
    else:
        return {
            "pass": True,
            "message": "GREEN — No known events in window.",
            "details": result["summary"],
            "search_queries": result["search_queries"],
            "web_searched": result["web_searched"],
        }


def run_full_checklist(client, symbol, expiration_date, risk_amount,
                       existing_positions=None, web_events=None):
    """Run the complete pre-trade checklist.

    Args:
        web_events: Optional list of events from web search. Each should be a
                    dict with: date, event, severity ("RED"/"YELLOW"), source.
                    Pass this after Claude runs web searches for the symbol.
    """
    if existing_positions is None:
        existing_positions = []

    print("=" * 60)
    print(f"  PRE-TRADE CHECKLIST: {symbol}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    all_pass = True

    # 1. Market conditions
    print("\n1. MARKET CONDITIONS")
    market, vix = check_market_conditions(client)
    for s in market["signals"]:
        print(f"   [OK] {s}")
    for w in market["warnings"]:
        print(f"   [!!] {w}")
        all_pass = False

    # 2. Earnings check
    print("\n2. EARNINGS CHECK")
    earnings = check_earnings(symbol, expiration_date)
    status = "[OK]" if earnings["pass"] else "[BLOCKED]"
    print(f"   {status} {earnings['message']}")
    if not earnings["pass"]:
        all_pass = False

    # 3. Correlation check
    print("\n3. CORRELATION CHECK")
    corr = check_correlation(symbol, existing_positions)
    status = "[OK]" if corr["pass"] else "[!!]"
    print(f"   {status} {corr['message']}")
    if not corr["pass"]:
        all_pass = False

    # 4. Position sizing
    print("\n4. POSITION SIZING")
    cash = get_cash_status(client)
    size = check_position_size(risk_amount, cash["net_available"])
    status = "[OK]" if size["pass"] else "[BLOCKED]"
    print(f"   {status} {size['message']}")
    if not size["pass"]:
        all_pass = False

    # 5. Loss streak + sizing consistency
    print("\n5. LOSS STREAK CHECK")
    streak = check_loss_streak()
    status = "[OK]" if streak["pass"] else "[BLOCKED]"
    print(f"   {status} {streak['message']}")
    if not streak["pass"]:
        all_pass = False

    print("\n6. SIZING CONSISTENCY")
    sizing = check_sizing_consistency()
    status = "[OK]" if sizing["pass"] else "[!!]"
    print(f"   {status} {sizing['message']}")
    if not sizing["pass"]:
        all_pass = False

    # 7. Event scan (FOMC, CPI, court cases, regulatory, etc.)
    print("\n7. EVENT SCAN")
    events = check_upcoming_events(symbol, expiration_date, web_events=web_events)
    if not events["pass"]:
        status = "[BLOCKED]"
        all_pass = False
    elif "YELLOW" in events["message"]:
        status = "[!!]"
    else:
        status = "[OK]"
    print(f"   {status} {events['message']}")
    if events["details"]:
        for line in events["details"].split("\n"):
            print(f"   {line}")
    if not events["web_searched"]:
        print("   [!!] WEB SEARCH REQUIRED — Run company-specific searches before trading.")

    # Verdict
    print("\n" + "=" * 60)
    if all_pass:
        print("  VERDICT: ALL CHECKS PASS. Trade is clear to execute.")
    else:
        print("  VERDICT: ONE OR MORE CHECKS FAILED. Review warnings above.")
    print("=" * 60)

    return all_pass


if __name__ == "__main__":
    from datetime import date
    client = get_client()
    run_full_checklist(
        client,
        symbol="NVDA",
        expiration_date=date(2026, 4, 24),
        risk_amount=4300,
        existing_positions=[],
    )
