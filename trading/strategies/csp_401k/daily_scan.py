"""
Daily market scan. Run pre-market or at open.

Checks:
1. Market conditions (VIX, SPY/QQQ direction)
2. Which watchlist stocks are down big (red-name put-premium context)
3. Whether options premium is worth selling today
4. Outputs premium-selling conditions only — options desk, never share-buy advice

Exit codes:
  0 = action recommended (notification worthy)
  1 = do nothing today (no notification needed)
"""
import json
import os
import sys
import requests
from datetime import datetime, timedelta
from pathlib import Path
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
from shared.auth import get_client
from shared.accounts import account_by_suffix, configured_account_suffix
from scan_log import log_scan, log_alert, log_no_action

from shared.notifications import post_message

WATCHLIST = [
    "NVDA", "GOOGL", "META", "AMZN", "TSM", "COIN", "AMD",
    "SHOP", "ASML", "NET", "NFLX", "AAPL", "HUBS", "MSFT",
    "TEAM",  # Atlassian — beat-up but 20%+ rev growth, switching-cost moat
    "IBIT",  # Bitcoin ETF — sample liquid-options watchlist member
]

# Thresholds
DCA_THRESHOLD = -3.0        # stock down X% today = red-name context (name kept for log continuity)
BIG_DIP_THRESHOLD = -5.0    # stock down X% = strongly red — premium likely richest here
VIX_ELEVATED = 25           # VIX above this = good for selling premium
MARKET_FEAR_THRESHOLD = -1.5  # SPY/QQQ down X% = fear day


def get_cash_status(client):
    """Check actual cash available in the 401k."""
    acct = account_by_suffix(client, configured_account_suffix())

    from schwab import client as sc
    resp = client.get_account(acct["hashValue"], fields=[sc.Client.Account.Fields.POSITIONS])
    resp.raise_for_status()
    sa = resp.json().get("securitiesAccount", {})
    bal = sa.get("currentBalances", {})

    cash_balance = bal.get("cashBalance", 0)
    available = bal.get("cashAvailableForTrading", 0)
    liquidation = bal.get("liquidationValue", 0)

    # Reconcile logged-open trades against what the account actually holds.
    # A recommendation logged as "open" but never filled must not lock collateral —
    # but a position that WAS live and is now gone is a fill, not a phantom, and must
    # be surfaced for closing rather than silently unlocked. reconcile.classify keeps
    # the observation history that tells those two apart (see that module's docstring).
    from trade_log import load_log
    import reconcile as rc
    log = load_log()
    open_trades = [t for t in log.get("trades", []) if t["status"] == "open"]
    results, rc_state = rc.classify(open_trades, sa.get("positions", []), rc.load_state())
    rc.save_state(rc_state)
    rc.warn(results)

    locked = rc.collateral_locked(results)
    net_available = max(cash_balance - locked, 0)

    return {
        "cash_balance": cash_balance,
        "available_for_trading": available,
        "liquidation_value": liquidation,
        "locked_collateral": locked,
        "net_available": net_available,
        "open_trades": rc.by_verdict(results, rc.CONFIRMED),
        "phantom_trades": rc.by_verdict(results, rc.PHANTOM),
        "closed_trades_to_book": rc.by_verdict(results, rc.LIKELY_CLOSED),
        "pending_trades": rc.by_verdict(results, rc.PENDING),
        "reconcile_results": results,
    }


def run_scan():
    client = get_client()

    # Check cash first — can't recommend what we can't afford
    cash = get_cash_status(client)

    # Fetch everything in one call
    all_symbols = WATCHLIST + ["SPY", "QQQ"]
    resp = client.get_quotes(all_symbols)
    resp.raise_for_status()
    data = resp.json()

    now = datetime.now()
    report = {"timestamp": now.isoformat(), "actions": [], "details": {}}

    # Market conditions
    spy_change = data["SPY"]["quote"].get("netPercentChange", 0)
    qqq_change = data["QQQ"]["quote"].get("netPercentChange", 0)

    # VIX - try known ticker variants (Schwab uses $VIX, not $VIX.X)
    vix = 0
    for vix_sym in ("$VIX", "$VIX.X", "VIX"):
        try:
            vix_resp = client.get_quotes([vix_sym])
            vix_resp.raise_for_status()
            price = vix_resp.json().get(vix_sym, {}).get("quote", {}).get("lastPrice", 0)
            if price and price > 0:
                vix = price
                break
        except Exception:
            continue

    report["details"]["spy"] = spy_change
    report["details"]["qqq"] = qqq_change
    report["details"]["vix"] = vix

    market_fear = spy_change <= MARKET_FEAR_THRESHOLD or qqq_change <= MARKET_FEAR_THRESHOLD
    vix_high = vix >= VIX_ELEVATED

    # Check each stock
    dca_candidates = []
    big_dips = []
    for sym in WATCHLIST:
        q = data[sym]["quote"]
        f = data[sym].get("fundamental", {})
        change = q.get("netPercentChange", 0)
        price = q.get("lastPrice", 0)
        pe = f.get("peRatio", 0)

        if change <= BIG_DIP_THRESHOLD:
            big_dips.append({"symbol": sym, "price": price, "change": change, "pe": pe})
        elif change <= DCA_THRESHOLD:
            dca_candidates.append({"symbol": sym, "price": price, "change": change, "pe": pe})

    # Build recommendation
    output_lines = []
    output_lines.append(f"=== DAILY SCAN {now.strftime('%Y-%m-%d %H:%M')} ===")
    output_lines.append(f"SPY: {spy_change:+.2f}%  QQQ: {qqq_change:+.2f}%  VIX: {vix:.1f}")
    output_lines.append(f"401k Cash: ${cash['cash_balance']:,.0f} | Locked: ${cash['locked_collateral']:,.0f} | Available: ~${cash['net_available']:,.0f}")
    if cash["open_trades"]:
        for t in cash["open_trades"]:
            output_lines.append(f"  Open: {t['symbol']} ${t['sell_strike']} {t['strategy']} (exp {t['expiration']})")
    output_lines.append("")

    action_needed = False

    # Down-big names: PREMIUM-SELLING context only. This desk is options-only
    # (CRON_PROMPT, 2026-07-07) — no share-buy / DCA advice ever comes from here;
    # the old "CONSIDER BUYING SHARES" / "DCA CANDIDATES" outputs predated the fund
    # architecture and mixed long-term-hold advice into the options channel. A big
    # red name is where put premium is richest (RULES.md §1 red-day rule); whether
    # it clears the gates is the screener's job, not this scan's.
    if big_dips or dca_candidates:
        action_needed = True
        output_lines.append(">>> RED NAMES TODAY — put-premium context (screener decides; never share-buy advice):")
        for s in sorted(big_dips + dca_candidates, key=lambda x: x["change"]):
            output_lines.append(f"    {s['symbol']} ${s['price']:.2f} ({s['change']:+.1f}%)")
        output_lines.append("")

    # Priority 3: Fear day = good for selling premium
    if market_fear or vix_high:
        action_needed = True
        reasons = []
        if market_fear:
            reasons.append(f"market down (SPY {spy_change:+.1f}%)")
        if vix_high:
            reasons.append(f"VIX elevated ({vix:.0f})")
        output_lines.append(f">>> PREMIUM SELLING CONDITIONS: FAVORABLE ({', '.join(reasons)})")
        output_lines.append("    Put spreads and covered calls will pay more today.")
        output_lines.append("")

    if not action_needed:
        output_lines.append(">>> NO ACTION TODAY")
        output_lines.append("    Market is calm, nothing notably red. Premiums are thin.")
        output_lines.append("    Sit tight and wait for a real fear day.")

    report["output"] = "\n".join(output_lines)
    report["action_needed"] = action_needed

    # Print report
    print(report["output"])

    # Save report to file for other systems to read
    report_path = os.path.join(os.path.dirname(__file__), "state", "last_scan.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    # Log everything
    log_scan("daily_scan", {
        "spy_change": spy_change,
        "qqq_change": qqq_change,
        "vix": vix,
        "cash_balance": cash["cash_balance"],
        "cash_available": cash["net_available"],
        "locked_collateral": cash["locked_collateral"],
        "open_trades": len(cash["open_trades"]),
        # key name kept for log continuity; semantics are now "red names, put context"
        "dca_candidates": [s["symbol"] for s in big_dips + dca_candidates],
        "premium_signal": market_fear or vix_high,
        "action_needed": action_needed,
    })

    if action_needed:
        # DO NOT send Slack from here. Scripts output data only.
        # The judgment agent writes a decision; the scheduler owns delivery.
        log_scan("daily_scan_signal", {
            "signals": [s["symbol"] for s in big_dips + dca_candidates],
            "premium_signal": market_fear or vix_high,
        })
    else:
        log_no_action(f"SPY {spy_change:+.1f}%, nothing notably red, premiums thin")

    return 0 if action_needed else 1


if __name__ == "__main__":
    sys.exit(run_scan())
