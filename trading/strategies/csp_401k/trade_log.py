"""
Trade log — tracks every trade for circuit breaker, sizing enforcement,
and performance analysis.

This is what makes the system mechanical. No memory, no emotion, just data.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

LOG_PATH = os.path.join(os.path.dirname(__file__), "state", "trade_log.json")


def load_log():
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH) as f:
            return json.load(f)
    return {"trades": [], "config": {"max_consecutive_losses": 3}}


def save_log(log):
    Path(LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "w") as f:
        json.dump(log, f, indent=2, default=str)


def log_trade_open(symbol, strategy, contracts, credit, max_loss, expiration,
                   sell_strike, buy_strike=None, notes="", journal_entry=None,
                   entry_vix=None):
    """Log a new trade when opened.

    entry_vix: $VIX at fill — record it, it conditions the 2x stop for this trade's
    whole life (RULES.md §4: stop auto-CUTs only on high-VIX entries; low-VIX entries
    get an advisory). None = unknown = treated as high-VIX (stop active, conservative).
    """
    log = load_log()
    trade = {
        "id": len(log["trades"]) + 1,
        "opened": datetime.now().isoformat(),
        "symbol": symbol,
        "strategy": strategy,  # "put_spread", "cash_secured_put", "covered_call"
        "contracts": contracts,
        "sell_strike": sell_strike,
        "buy_strike": buy_strike,
        "credit": credit,
        "max_loss": max_loss,
        "expiration": expiration,
        "entry_vix": entry_vix,
        "status": "open",
        "closed": None,
        "result": None,  # "win", "loss", "break_even"
        "pnl": None,
        "notes": notes,
        # Journal: structured reasoning for audit
        "journal": journal_entry or {},
        # Filled by expiry_check.py on expiration day
        "expiry_snapshot": None,
    }
    log["trades"].append(trade)
    save_log(log)
    print(f"Trade #{trade['id']} logged: {strategy} on {symbol}, {contracts} contracts, ${credit} credit")
    return trade


def log_trade_close(trade_id, result, pnl, notes="", journal_exit=None):
    """Log a trade close (expiration, assignment, or early close)."""
    log = load_log()
    for trade in log["trades"]:
        if trade["id"] == trade_id:
            trade["status"] = "closed"
            trade["closed"] = datetime.now().isoformat()
            trade["result"] = result
            trade["pnl"] = pnl
            trade["close_notes"] = notes
            if journal_exit:
                if "journal" not in trade:
                    trade["journal"] = {}
                trade["journal"]["exit"] = journal_exit
            break
    save_log(log)
    print(f"Trade #{trade_id} closed: {result}, P&L: ${pnl:+,.2f}")


def log_expiry_snapshot(trade_id, stock_price, option_value, would_have_pnl):
    """Record what happened at expiration for a closed trade.

    Called by expiry_check.py on expiration day. One number per trade.
    After 20-30 trades, this data answers: "does closing early help or hurt?"
    """
    log = load_log()
    for trade in log["trades"]:
        if trade["id"] == trade_id:
            trade["expiry_snapshot"] = {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "stock_price": stock_price,
                "option_value": option_value,
                "would_have_pnl": would_have_pnl,
                "actual_pnl": trade.get("pnl", 0),
                "early_close_delta": trade.get("pnl", 0) - would_have_pnl,
            }
            break
    save_log(log)
    print(f"Trade #{trade_id} expiry snapshot: stock ${stock_price:.2f}, "
          f"option ${option_value:.2f}, would-have P&L ${would_have_pnl:+,.0f}, "
          f"actual ${trade.get('pnl', 0):+,.0f}, delta ${trade.get('pnl', 0) - would_have_pnl:+,.0f}")


def check_loss_streak():
    """Check if we've hit the circuit breaker."""
    log = load_log()
    max_losses = log["config"]["max_consecutive_losses"]

    closed = [t for t in log["trades"] if t["status"] == "closed"]
    if len(closed) < max_losses:
        return {"pass": True, "streak": 0, "message": f"Only {len(closed)} trades closed. No streak concern."}

    recent = closed[-max_losses:]
    consecutive_losses = all(t["result"] == "loss" for t in recent)

    if consecutive_losses:
        return {
            "pass": False,
            "streak": max_losses,
            "message": f"CIRCUIT BREAKER: {max_losses} consecutive losses. "
                       f"Pause trading and reassess strategy before continuing."
        }

    # Count current streak
    streak = 0
    for t in reversed(closed):
        if t["result"] == "loss":
            streak += 1
        else:
            break

    return {"pass": True, "streak": streak, "message": f"Current loss streak: {streak}/{max_losses}"}


def check_sizing_consistency():
    """Ensure we're not sizing up after wins (behavioral leak)."""
    log = load_log()
    closed = [t for t in log["trades"] if t["status"] == "closed"]

    if len(closed) < 2:
        return {"pass": True, "message": "Not enough history to check sizing drift."}

    last = closed[-1]
    current_open = [t for t in log["trades"] if t["status"] == "open"]

    if last["result"] == "win" and current_open:
        for t in current_open:
            if t["max_loss"] > last["max_loss"] * 1.5:
                return {
                    "pass": False,
                    "message": f"WARNING: New position risk (${t['max_loss']:,.0f}) is >1.5x "
                               f"last trade (${last['max_loss']:,.0f}). Are you sizing up after a win?"
                }

    return {"pass": True, "message": "Position sizing is consistent."}


def get_performance_summary():
    """Show overall strategy performance."""
    log = load_log()
    closed = [t for t in log["trades"] if t["status"] == "closed"]
    open_trades = [t for t in log["trades"] if t["status"] == "open"]

    if not closed:
        print("\nNo closed trades yet.")
        if open_trades:
            print(f"{len(open_trades)} open trade(s):")
            for t in open_trades:
                print(f"  #{t['id']}: {t['symbol']} {t['strategy']} "
                      f"${t['credit']} credit, expires {t['expiration']}")
        return

    wins = [t for t in closed if t["result"] == "win"]
    losses = [t for t in closed if t["result"] == "loss"]
    total_pnl = sum(t["pnl"] for t in closed if t["pnl"] is not None)
    total_credit = sum(t["credit"] for t in closed)
    total_max_loss = sum(t["max_loss"] for t in closed)

    print("\n=== TRADING PERFORMANCE ===")
    print(f"Total trades: {len(closed)} closed, {len(open_trades)} open")
    print(f"Win rate: {len(wins)}/{len(closed)} ({len(wins)/len(closed)*100:.0f}%)")
    print(f"Total P&L: ${total_pnl:+,.2f}")
    print(f"Total credit collected: ${total_credit:,.2f}")
    print(f"Total capital risked: ${total_max_loss:,.2f}")
    print(f"Return on risk: {total_pnl/total_max_loss*100:+.1f}%" if total_max_loss > 0 else "")

    # Loss streak
    streak = check_loss_streak()
    print(f"Loss streak: {streak['streak']}")
    if not streak["pass"]:
        print(f"  >>> {streak['message']}")

    if open_trades:
        print(f"\nOpen positions:")
        for t in open_trades:
            print(f"  #{t['id']}: {t['symbol']} {t['strategy']} "
                  f"${t['credit']} credit, expires {t['expiration']}")


if __name__ == "__main__":
    get_performance_summary()
