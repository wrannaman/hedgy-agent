"""Independent index-spread journal; private fills live in ignored local state.

This log is separate from the cash-secured-put journal and never implies an order
was placed. Record only explicit fills supplied by the account owner.
"""
import json
from datetime import datetime
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parent / "state" / "trade_log.json"


def load_log():
    if LOG_PATH.exists():
        return json.loads(LOG_PATH.read_text())
    return {"trades": []}


def save_log(log):
    LOG_PATH.parent.mkdir(exist_ok=True)
    LOG_PATH.write_text(json.dumps(log, indent=2, default=str))


def log_trade_open(symbol, contracts, credit, max_loss, expiration,
                   sell_strike, buy_strike, notes=""):
    """Log a filled spread. credit/max_loss are TOTAL dollars for the position."""
    log = load_log()
    trade = {
        "id": len(log["trades"]) + 1,
        "opened": datetime.now().isoformat(),
        "symbol": symbol,
        "strategy": "put_spread",
        "contracts": contracts,
        "sell_strike": sell_strike,
        "buy_strike": buy_strike,
        "credit": credit,
        "max_loss": max_loss,
        "width_dollars": round((sell_strike - buy_strike) * 100 * contracts),
        "expiration": expiration,
        "status": "open",
        "closed": None,
        "result": None,
        "pnl": None,
        "notes": notes,
    }
    log["trades"].append(trade)
    save_log(log)
    return trade


def log_trade_close(trade_id, result, pnl, notes=""):
    """Close a trade: result in win|loss|break_even, pnl in dollars (realized)."""
    log = load_log()
    for t in log["trades"]:
        if t["id"] == trade_id and t["status"] == "open":
            t.update({"status": "closed", "closed": datetime.now().isoformat(),
                      "result": result, "pnl": pnl})
            if notes:
                t["notes"] = (t.get("notes") or "") + f" | close: {notes}"
            save_log(log)
            return t
    raise ValueError(f"no open trade with id {trade_id}")


def open_width_dollars():
    """Total open spread width — the number the deployment cap gates on."""
    return sum(t.get("width_dollars", 0) for t in load_log()["trades"]
               if t.get("status") == "open")
