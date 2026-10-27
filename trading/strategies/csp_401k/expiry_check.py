"""
Expiration day snapshot for closed trades.

Runs daily via cron. On most days, does nothing.
On expiration days, records the stock price and what P&L would have
been if the trade was held to expiration instead of closed early.

After 20-30 trades, this data answers: "does closing early help or hurt?"
One number per trade. No daily shadow tracking.
"""
import sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.auth import get_client
from trade_log import load_log, log_expiry_snapshot


def check_expiring_trades():
    today = datetime.now().strftime("%Y-%m-%d")
    log = load_log()

    # Find closed trades that expire today and don't have a snapshot yet
    expiring = [
        t for t in log["trades"]
        if t["status"] == "closed"
        and t.get("expiration", "")[:10] == today
        and t.get("expiry_snapshot") is None
    ]

    if not expiring:
        print(f"No closed trades expiring today ({today}).")
        return 1

    client = get_client()

    for trade in expiring:
        symbol = trade["symbol"]
        strike = trade["sell_strike"]
        credit = trade["credit"]
        contracts = trade["contracts"]

        # Get current stock price
        resp = client.get_quotes([symbol])
        resp.raise_for_status()
        q = resp.json()[symbol]["quote"]
        stock_price = q["lastPrice"]

        # For puts: intrinsic value at expiration
        if "put" in trade["strategy"] or trade["strategy"] == "cash_secured_put":
            option_value = max(0, strike - stock_price) * 100 * contracts
        else:
            option_value = 0

        # What P&L would have been if held to expiration
        total_credit = credit  # already in dollars (cents * 100 done at entry)
        would_have_pnl = total_credit - option_value

        log_expiry_snapshot(trade["id"], stock_price, option_value, would_have_pnl)

        # Summary
        actual = trade.get("pnl", 0)
        delta = actual - would_have_pnl
        if delta > 0:
            print(f"  Closing early COST ${abs(delta):,.0f} — would have made more holding.")
        elif delta < 0:
            print(f"  Closing early SAVED ${abs(delta):,.0f} — holding would have been worse.")
        else:
            print(f"  Break even — same result either way.")

    return 0


if __name__ == "__main__":
    sys.exit(check_expiring_trades())
