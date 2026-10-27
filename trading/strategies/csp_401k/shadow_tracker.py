"""
Shadow tracker — continues monitoring closed trades until expiration.

After closing a trade early (e.g., 50% profit rule), this tracks what
WOULD have happened if we held. Snapshots the option price daily so
we can run a postmortem at expiration.

Run daily via cron after market close.

Usage:
    python shadow_tracker.py          # snapshot all active shadows
    python shadow_tracker.py --list   # show current shadow trades
"""
import json
import os
import sys
from datetime import datetime, date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.auth import get_client
from trade_log import load_log

SHADOW_PATH = os.path.join(os.path.dirname(__file__), "state", "shadow_log.json")


def load_shadows():
    if os.path.exists(SHADOW_PATH):
        with open(SHADOW_PATH) as f:
            return json.load(f)
    return {"shadows": []}


def save_shadows(data):
    with open(SHADOW_PATH, "w") as f:
        json.dump(data, f, indent=2, default=str)


def register_closed_trade(trade):
    """Add a closed trade to shadow tracking."""
    shadows = load_shadows()

    # Don't double-register
    if any(s["trade_id"] == trade["id"] for s in shadows["shadows"]):
        return

    shadows["shadows"].append({
        "trade_id": trade["id"],
        "symbol": trade["symbol"],
        "strategy": trade["strategy"],
        "sell_strike": trade["sell_strike"],
        "credit": trade["credit"],
        "contracts": trade.get("contracts", 1),
        "expiration": trade["expiration"],
        "opened": trade["opened"],
        "closed": trade["closed"],
        "actual_pnl": trade["pnl"],
        "close_price": None,  # filled by first snapshot or manually
        "stock_at_close": None,
        "snapshots": [],
        "final_outcome": None,  # filled at expiration
    })
    save_shadows(shadows)
    print(f"Shadow registered: Trade #{trade['id']} {trade['symbol']} (exp {trade['expiration']})")


def snapshot_all(client=None):
    """Take a daily snapshot of all active shadow trades."""
    if client is None:
        client = get_client()

    shadows = load_shadows()
    today = date.today()
    now = datetime.now()

    active = [s for s in shadows["shadows"]
              if s["final_outcome"] is None
              and datetime.strptime(s["expiration"], "%Y-%m-%d").date() >= today]

    if not active:
        print("No active shadow trades to track.")
        return

    for shadow in active:
        symbol = shadow["symbol"]
        strike = shadow["sell_strike"]
        exp_str = shadow["expiration"]

        # Get stock price
        resp = client.get_quotes([symbol])
        resp.raise_for_status()
        q = resp.json()[symbol]["quote"]
        stock_price = q["lastPrice"]

        # Get option price
        from datetime import timedelta
        resp2 = client.get_option_chain(
            symbol=symbol,
            contract_type=client.Options.ContractType.PUT,
            strike_count=30,
            from_date=today + timedelta(days=1),
            to_date=today + timedelta(days=60),
        )
        resp2.raise_for_status()
        chain = resp2.json()

        option_mid = None
        option_bid = None
        option_ask = None
        dte = None

        for exp, sd in chain.get("putExpDateMap", {}).items():
            for sk, cl in sd.items():
                for c in cl:
                    contract_exp = c.get("expirationDate", "")[:10]
                    if c["strikePrice"] == strike and contract_exp == exp_str:
                        option_bid = c["bid"]
                        option_ask = c["ask"]
                        option_mid = (option_bid + option_ask) / 2
                        dte = c["daysToExpiration"]

        if option_mid is None:
            print(f"  Could not find {symbol} ${strike} put for {exp_str}")
            continue

        # Calculate what P&L would be if still holding
        n = shadow.get("contracts", 1)
        credit_per_share = shadow["credit"] / (100 * n)
        hypothetical_pnl = (credit_per_share - option_ask) * 100 * n

        snapshot = {
            "date": str(today),
            "time": now.strftime("%H:%M"),
            "stock_price": stock_price,
            "option_mid": round(option_mid, 2),
            "option_bid": option_bid,
            "option_ask": option_ask,
            "dte": dte,
            "hypothetical_pnl": round(hypothetical_pnl, 2),
        }

        # Deduplicate: one snapshot per day
        existing_dates = [s["date"] for s in shadow["snapshots"]]
        if str(today) not in existing_dates:
            shadow["snapshots"].append(snapshot)

        pct_of_max = (credit_per_share - option_mid) / credit_per_share * 100

        print(f"  {symbol} ${strike}P (exp {exp_str}) | "
              f"Stock: ${stock_price:.2f} | Put: ${option_mid:.2f} | "
              f"If held: ${hypothetical_pnl:+,.0f} ({pct_of_max:.0f}% of max) | "
              f"Actual closed at: ${shadow['actual_pnl']:+,.0f} | "
              f"DTE: {dte}")

    # Check for expired shadows
    for shadow in shadows["shadows"]:
        exp_date = datetime.strptime(shadow["expiration"], "%Y-%m-%d").date()
        if exp_date < today and shadow["final_outcome"] is None:
            # Option expired — determine final outcome
            if shadow["snapshots"]:
                last = shadow["snapshots"][-1]
                stock_at_exp = last["stock_price"]
            else:
                stock_at_exp = None

            if stock_at_exp and stock_at_exp > shadow["sell_strike"]:
                # Expired worthless — full profit
                shadow["final_outcome"] = {
                    "result": "expired_worthless",
                    "hypothetical_pnl": shadow["credit"],
                    "actual_pnl": shadow["actual_pnl"],
                    "difference": shadow["credit"] - shadow["actual_pnl"],
                    "note": f"Would have made ${shadow['credit']} vs actual ${shadow['actual_pnl']}. "
                            f"Left ${shadow['credit'] - shadow['actual_pnl']} on the table but freed capital earlier."
                }
            elif stock_at_exp and stock_at_exp <= shadow["sell_strike"]:
                # Assigned — would have been forced to buy shares
                n = shadow.get("contracts", 1)
                assignment_cost = shadow["sell_strike"] * 100 * n
                effective_cost = shadow["sell_strike"] - shadow["credit"] / (100 * n)
                shadow["final_outcome"] = {
                    "result": "would_have_been_assigned",
                    "stock_at_expiration": stock_at_exp,
                    "hypothetical_pnl": (stock_at_exp - effective_cost) * 100 * n,
                    "actual_pnl": shadow["actual_pnl"],
                    "note": f"Would have been assigned 100 shares at ${shadow['sell_strike']}. "
                            f"Closing early was the right call."
                }
            if shadow["final_outcome"] is None:
                print(f"  EXPIRED: Trade #{shadow['trade_id']} {shadow['symbol']} — unresolved (no snapshot price at expiration)")
            else:
                print(f"  EXPIRED: Trade #{shadow['trade_id']} {shadow['symbol']} — {shadow['final_outcome']['result']}")

    save_shadows(shadows)


def postmortem(trade_id=None):
    """Generate a comparison report for closed shadow trades."""
    shadows = load_shadows()

    targets = shadows["shadows"]
    if trade_id:
        targets = [s for s in targets if s["trade_id"] == trade_id]

    for shadow in targets:
        print(f"\n{'='*60}")
        print(f"  POSTMORTEM: Trade #{shadow['trade_id']} — {shadow['symbol']} ${shadow['sell_strike']}P")
        print(f"  Opened: {shadow['opened'][:10]} | Closed: {shadow['closed'][:10]} | Exp: {shadow['expiration']}")
        print(f"{'='*60}")
        print(f"\n  Credit collected: ${shadow['credit']}")
        print(f"  Actual P&L (closed early): ${shadow['actual_pnl']:+,}")

        if shadow["final_outcome"]:
            fo = shadow["final_outcome"]
            print(f"  If held to expiration: ${fo['hypothetical_pnl']:+,}")
            print(f"  Outcome: {fo['result']}")
            print(f"  {fo['note']}")
        elif shadow["snapshots"]:
            last = shadow["snapshots"][-1]
            print(f"\n  Latest shadow ({last['date']}):")
            print(f"    Stock: ${last['stock_price']:.2f} | Put: ${last['option_mid']:.2f}")
            print(f"    If still holding: ${last['hypothetical_pnl']:+,.0f}")
            diff = last["hypothetical_pnl"] - shadow["actual_pnl"]
            if diff > 0:
                print(f"    Holding would be +${diff:.0f} better right now")
            else:
                print(f"    Closing early was +${abs(diff):.0f} better right now")

        if shadow["snapshots"]:
            print(f"\n  Daily P&L if held:")
            for snap in shadow["snapshots"]:
                diff = snap["hypothetical_pnl"] - shadow["actual_pnl"]
                marker = " <-- closed here" if snap["date"] == shadow["closed"][:10] else ""
                better = "hold better" if diff > 0 else "close better"
                print(f"    {snap['date']}: put ${snap['option_mid']:.2f} | "
                      f"P&L ${snap['hypothetical_pnl']:+,.0f} | "
                      f"vs actual: {'+' if diff >= 0 else ''}{diff:.0f} ({better}){marker}")


if __name__ == "__main__":
    if "--list" in sys.argv:
        shadows = load_shadows()
        for s in shadows["shadows"]:
            status = "EXPIRED" if s["final_outcome"] else "TRACKING"
            print(f"  [{status}] Trade #{s['trade_id']} {s['symbol']} ${s['sell_strike']}P "
                  f"(exp {s['expiration']}) | Actual P&L: ${s['actual_pnl']:+,}")
    elif "--postmortem" in sys.argv:
        tid = None
        idx = sys.argv.index("--postmortem")
        if idx + 1 < len(sys.argv):
            tid = int(sys.argv[idx + 1])
        postmortem(tid)
    else:
        # Register any closed trades not yet shadowed
        log = load_log()
        for trade in log["trades"]:
            if trade["status"] == "closed":
                register_closed_trade(trade)

        # Take daily snapshots
        print(f"=== SHADOW TRACKER {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")
        snapshot_all()
